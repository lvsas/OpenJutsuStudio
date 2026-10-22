"""Bounded seed attempts: one frozen request, several candidates, one choice.

A hunt is not a new pipeline. It refines the direction once, then submits the same
frozen request with different seeds, sequentially, on the single GPU worker. Each
candidate is an ordinary native operation with its own durable record, so a partial
failure resumes without repeating a candidate that already produced a take.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path

_ID = re.compile(r'[0-9a-f]{32}\Z')
ROOT = ('native-attempts',)
MAX_CANDIDATES = 4
_STATUS_PENDING = 'pending'
_STATUS_RUNNING = 'running'
_STATUS_DONE = 'done'
_STATUS_FAILED = 'failed'


class AttemptError(ValueError):
    pass


def _folder(root, attempt_id):
    if not isinstance(attempt_id, str) or not _ID.fullmatch(attempt_id):
        raise AttemptError('A valid attempt identifier is required.')
    return Path(root).joinpath(*ROOT) / attempt_id


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    with staging.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'))
        stream.flush()
        os.fsync(stream.fileno())
    staging.replace(path)


def load(root, attempt_id) -> dict:
    path = _folder(root, attempt_id) / 'attempt.json'
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        raise AttemptError('Attempt not found.') from None
    except (OSError, ValueError):
        raise AttemptError('The attempt record cannot be read.') from None
    if not isinstance(value, dict) or not isinstance(value.get('candidates'), list):
        raise AttemptError('The attempt record cannot be read.')
    return value


def create(root, *, take_id: str, prompt: str, raw_frames: int, seeds) -> dict:
    """Freeze the hunt before any GPU work; seeds are the only variable."""
    if not isinstance(take_id, str) or not _ID.fullmatch(take_id):
        raise AttemptError('A valid take identifier is required.')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise AttemptError('A direction is required for every candidate.')
    if type(raw_frames) is not int or raw_frames < 5 or raw_frames > 3600 or (raw_frames - 5) % 17:
        raise AttemptError('H3 frames must follow the native 17k+5 grid.')
    seeds = list(seeds)
    if not 1 <= len(seeds) <= MAX_CANDIDATES:
        raise AttemptError(f'Ask for between 1 and {MAX_CANDIDATES} candidates.')
    if len(set(seeds)) != len(seeds) or any(type(s) is not int or not 0 <= s < 2 ** 64 for s in seeds):
        raise AttemptError('Seeds must be distinct whole numbers below 2^64.')
    attempt = {'version': 1, 'attempt_id': uuid.uuid4().hex, 'take_id': take_id,
               'prompt': prompt, 'raw_frames': raw_frames, 'status': _STATUS_PENDING,
               'refined_prompt': None, 'error': None,
               'candidates': [{'operation_id': uuid.uuid4().hex, 'seed': seed,
                               'status': _STATUS_PENDING, 'take_id': None, 'error': None}
                              for seed in seeds]}
    _atomic(_folder(root, attempt['attempt_id']) / 'attempt.json', attempt)
    return attempt


def public(attempt: dict) -> dict:
    return {'attempt_id': attempt['attempt_id'], 'take_id': attempt['take_id'],
            'status': attempt['status'], 'error': attempt['error'],
            'candidates': [{'seed': c['seed'], 'status': c['status'],
                            'take_id': c['take_id'], 'error': c['error'],
                            'url': (f"/api/continuity/takes/{c['take_id']}" if c['take_id'] else None)}
                           for c in attempt['candidates']]}


def _update(root, attempt_id, mutate):
    folder = _folder(root, attempt_id)
    attempt = load(root, attempt_id)
    mutate(attempt)
    _atomic(folder / 'attempt.json', attempt)
    return attempt


def run(root, attempt_id, *, refine, submit) -> dict:
    """Sequentially produce candidates; a failed one never erases the others."""
    attempt = load(root, attempt_id)
    try:
        refined = refine(attempt['prompt'], attempt['take_id'])
    except Exception as error:  # noqa: BLE001 - the message is surfaced, never guessed
        _update(root, attempt_id, lambda a: a.update(status=_STATUS_FAILED,
                error=f'The direction could not be prepared: {error}'))
        return load(root, attempt_id)
    _update(root, attempt_id, lambda a: a.update(refined_prompt=refined, status=_STATUS_RUNNING))
    for index, candidate in enumerate(load(root, attempt_id)['candidates']):
        if candidate['status'] == _STATUS_DONE:
            continue
        _update(root, attempt_id, lambda a, i=index: a['candidates'][i].update(status=_STATUS_RUNNING))
        try:
            take_id = submit(candidate['operation_id'], refined, candidate['seed'],
                             attempt['raw_frames'], attempt['take_id'])
        except Exception as error:  # noqa: BLE001
            _update(root, attempt_id, lambda a, i=index, e=error: a['candidates'][i].update(
                status=_STATUS_FAILED, error=str(e)[:400]))
            continue
        _update(root, attempt_id, lambda a, i=index, t=take_id: a['candidates'][i].update(
            status=_STATUS_DONE, take_id=t))
    final = load(root, attempt_id)
    done = [c for c in final['candidates'] if c['status'] == _STATUS_DONE]
    _update(root, attempt_id, lambda a: a.update(
        status=_STATUS_DONE if done else _STATUS_FAILED,
        error=None if done else 'No candidate completed.'))
    return load(root, attempt_id)


class Worker:
    """One background thread: GPU submissions are serialized, never parallel."""

    def __init__(self, root, *, refine, submit):
        self.root = Path(root)
        self._refine = refine
        self._submit = submit
        self._queue: list[str] = []
        self._lock = threading.Lock()
        self._thread = None

    def start(self, attempt_id: str) -> None:
        with self._lock:
            if attempt_id in self._queue:
                return
            self._queue.append(attempt_id)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, daemon=True,
                                                name='native-attempt-worker')
                self._thread.start()

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._thread = None
                    return
                attempt_id = self._queue.pop(0)
            try:
                run(self.root, attempt_id, refine=self._refine, submit=self._submit)
            except Exception as error:  # noqa: BLE001 - the record carries the failure
                try:
                    _update(self.root, attempt_id, lambda a, e=error: a.update(
                        status=_STATUS_FAILED, error=str(e)[:400]))
                except Exception:  # noqa: BLE001 - nothing further can be recorded
                    pass
