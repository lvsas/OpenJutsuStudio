"""Bounded seed attempts: one frozen request, several candidates, one choice.

A hunt is not a new pipeline. It refines the direction once, then submits the same
frozen request with different seeds, sequentially, on the single GPU worker. Each
candidate is an ordinary native operation with its own durable record. Completed
candidates are never resubmitted; interrupted submissions require explicit recovery.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
import fcntl
from contextlib import contextmanager
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


class AttemptConflict(AttemptError):
    """A request identity is already bound to a different frozen payload."""


class AttemptNotFound(AttemptError):
    """No persisted record matches the supplied identity."""


def _identifier(value, kind):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise AttemptError(f'A valid {kind} identifier is required.')


@contextmanager
def _file_lock(path, *, blocking=True):
    # Each caller opens a separate descriptor: flock serializes threads as well
    # as processes on Linux. Never unlink a lock file (that would split locks).
    with path.open('a+b') as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


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
        raise AttemptNotFound('Attempt not found.') from None
    except (OSError, ValueError):
        raise AttemptError('The attempt record cannot be read.') from None
    required = {'attempt_id', 'take_id', 'prompt', 'raw_frames', 'status', 'error', 'candidates'}
    candidate_keys = {'operation_id', 'seed', 'status', 'take_id', 'error'}
    if (not isinstance(value, dict) or not required <= value.keys()
            or not isinstance(value['candidates'], list) or not value['candidates']
            or any(not isinstance(c, dict) or not candidate_keys <= c.keys()
                   for c in value['candidates'])):
        raise AttemptError('The attempt record cannot be read.')
    return value


def _records(root):
    # Read existing records directly; no request index, cache or second store.
    paths = Path(root).joinpath(*ROOT).glob('*/attempt.json')
    ordered = sorted((p for p in paths if _ID.fullmatch(p.parent.name)),
                     key=lambda p: (p.stat().st_mtime_ns, p.parent.name), reverse=True)
    return [load(root, p.parent.name) for p in ordered]


def by_request(root, take_id, request_id) -> dict:
    """Read-only recovery, scoped to a Take; never enqueue or create anything."""
    _identifier(take_id, 'take')
    _identifier(request_id, 'request')
    for attempt in _records(root):
        if attempt['take_id'] == take_id and attempt.get('request_id') == request_id:
            return attempt
    raise AttemptNotFound('Attempt not found.')


def list_for_take(root, take_id) -> list[dict]:
    """Include legacy attempts without a request_id, most recently updated first."""
    _identifier(take_id, 'take')
    return [attempt for attempt in _records(root) if attempt['take_id'] == take_id]


def _validate(*, take_id, prompt, raw_frames, seeds, request_id):
    _identifier(take_id, 'take')
    if request_id is not None:
        _identifier(request_id, 'request')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise AttemptError('A direction is required for every candidate.')
    if type(raw_frames) is not int or raw_frames < 5 or raw_frames > 3600 or (raw_frames - 5) % 17:
        raise AttemptError('H3 frames must follow the native 17k+5 grid.')
    try:
        seeds = list(seeds)
    except TypeError:
        raise AttemptError('Seeds must be a sequence of whole numbers.') from None
    if not 1 <= len(seeds) <= MAX_CANDIDATES:
        raise AttemptError(f'Ask for between 1 and {MAX_CANDIDATES} candidates.')
    if any(type(s) is not int or not 0 <= s < 2 ** 64 for s in seeds) or len(set(seeds)) != len(seeds):
        raise AttemptError('Seeds must be distinct whole numbers below 2^64.')
    return seeds


def create(root, *, take_id: str, prompt: str, raw_frames: int, seeds,
           request_id: str | None = None) -> dict:
    """Legacy internal callers may omit the request identity."""
    attempt, _ = create_or_get(root, take_id=take_id, prompt=prompt,
                               raw_frames=raw_frames, seeds=seeds, request_id=request_id)
    return attempt


def create_or_get(root, *, take_id: str, prompt: str, raw_frames: int, seeds,
                  request_id: str | None = None) -> tuple[dict, bool]:
    """Return (record, created); persist identity and intent in one locked write.

    Only the caller receiving created=True may queue work. A crash between this
    write and queueing leaves a recoverable pending record, not an automatic retry.
    """
    seeds = _validate(take_id=take_id, prompt=prompt, raw_frames=raw_frames,
                      seeds=seeds, request_id=request_id)
    store = Path(root).joinpath(*ROOT)
    store.mkdir(parents=True, exist_ok=True)
    with _file_lock(store / '.create.lock'):
        if request_id is not None:
            for existing in _records(root):
                if existing.get('request_id') != request_id:
                    continue
                intent = (existing['take_id'], existing['prompt'], existing['raw_frames'],
                          [c['seed'] for c in existing['candidates']])
                if intent != (take_id, prompt, raw_frames, seeds):
                    raise AttemptConflict('This request identifier already has a different frozen payload.')
                return existing, False
        attempt = {'version': 1, 'attempt_id': uuid.uuid4().hex, 'take_id': take_id,
                   'prompt': prompt, 'raw_frames': raw_frames, 'status': _STATUS_PENDING,
                   'refined_prompt': None, 'error': None,
                   'candidates': [{'operation_id': uuid.uuid4().hex, 'seed': seed,
                                   'status': _STATUS_PENDING, 'take_id': None, 'error': None}
                                  for seed in seeds]}
        if request_id is not None:
            attempt['request_id'] = request_id
        _atomic(_folder(root, attempt['attempt_id']) / 'attempt.json', attempt)
        return attempt, True


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


def _mark_interrupted(root, attempt_id):
    def block(attempt):
        uncertain = any(c['status'] in (_STATUS_RUNNING, 'unknown') for c in attempt['candidates'])
        unfinished = any(c['status'] == _STATUS_PENDING for c in attempt['candidates'])
        completed = any(c['status'] == _STATUS_DONE for c in attempt['candidates'])
        # A crash can also land after the final durable candidate write and
        # before the attempt summary. Preserve that known completion accurately.
        if not uncertain and not unfinished:
            attempt.update(status=_STATUS_DONE if completed else _STATUS_FAILED,
                           error=None if completed else 'No candidate completed.')
            return
        attempt.update(status=_STATUS_FAILED, error=(
            'A candidate outcome is unknown; explicit operation recovery is required.' if uncertain else
            'The server interrupted preparation or queued work; nothing was automatically restarted.'))
        for candidate in attempt['candidates']:
            if candidate['status'] == _STATUS_RUNNING:
                candidate.update(status='unknown', error='Submission outcome unknown; not resubmitted.')
            elif candidate['status'] == _STATUS_PENDING:
                candidate.update(status=_STATUS_FAILED, error='Not started before the server interruption.')
    return _update(root, attempt_id, block)


def reconcile_interrupted(root):
    """Startup-only checkpoint repair; never submit or mutate through a GET.

    A held run lock belongs to a live executor and must be left alone. An
    abandoned running or pending record is made terminal while retaining every
    completed candidate. Neither remote outcomes nor replacement Takes are
    invented. Call only at startup of the single scheduler for this work root.
    """
    changed = []
    for record in _records(root):
        if record['status'] not in (_STATUS_PENDING, _STATUS_RUNNING):
            continue
        attempt_id = record['attempt_id']
        with _file_lock(_folder(root, attempt_id) / '.run.lock', blocking=False) as acquired:
            if not acquired:
                continue
            current = load(root, attempt_id)
            if current['status'] not in (_STATUS_PENDING, _STATUS_RUNNING):
                continue
            _mark_interrupted(root, attempt_id)
            changed.append(attempt_id)
    return changed


def run(root, attempt_id, *, refine, submit) -> dict:
    """Run under a nonblocking process lock; a concurrent call is read-only."""
    load(root, attempt_id)  # Do not create directories for an unknown attempt.
    with _file_lock(_folder(root, attempt_id) / '.run.lock', blocking=False) as acquired:
        if not acquired:
            return load(root, attempt_id)
        try:
            return _run_locked(root, attempt_id, refine=refine, submit=submit)
        except Exception as error:  # noqa: BLE001 - record failures while still locked
            return _update(root, attempt_id, lambda a: a.update(
                status=_STATUS_FAILED, error=str(error)[:400]))


def _run_locked(root, attempt_id, *, refine, submit):
    attempt = load(root, attempt_id)
    if any(c['status'] in ('running', 'unknown') for c in attempt['candidates']):
        if any(c['status'] == 'running' for c in attempt['candidates']):
            return _mark_interrupted(root, attempt_id)
        return attempt
    if all(c['status'] == _STATUS_DONE for c in attempt['candidates']):
        return attempt
    refined = attempt.get('refined_prompt')
    if refined is None:
        try:
            refined = refine(attempt['prompt'], attempt['take_id'])
        except Exception as error:  # noqa: BLE001
            return _update(root, attempt_id, lambda a: a.update(status=_STATUS_FAILED,
                           error=f'The direction could not be prepared: {error}'[:400]))
    _update(root, attempt_id, lambda a: a.update(
        refined_prompt=refined, status=_STATUS_RUNNING, error=None))
    for index, candidate in enumerate(load(root, attempt_id)['candidates']):
        if candidate['status'] == _STATUS_DONE:
            continue
        _update(root, attempt_id, lambda a, i=index: a['candidates'][i].update(
            status=_STATUS_RUNNING, error=None))
        try:
            take_id = submit(candidate['operation_id'], refined, candidate['seed'],
                             attempt['raw_frames'], attempt['take_id'])
        except Exception as error:  # noqa: BLE001
            _update(root, attempt_id, lambda a, i=index, e=error: a['candidates'][i].update(
                status=_STATUS_FAILED, error=str(e)[:400]))
            continue
        _update(root, attempt_id, lambda a, i=index, t=take_id: a['candidates'][i].update(
            status=_STATUS_DONE, take_id=t, error=None))
    final = load(root, attempt_id)
    done = [c for c in final['candidates'] if c['status'] == _STATUS_DONE]
    return _update(root, attempt_id, lambda a: a.update(
        status=_STATUS_DONE if done else _STATUS_FAILED,
        error=None if done else 'No candidate completed.'))


class Worker:
    """One background thread: GPU submissions are serialized, never parallel."""

    def __init__(self, root, *, refine, submit):
        self.root = Path(root)
        self._refine = refine
        self._submit = submit
        self._queue: list[str] = []
        self._active: set[str] = set()
        self._lock = threading.Lock()
        self._thread = None

    def reconcile(self):
        """Repair abandoned checkpoints before serving recovery endpoints."""
        return reconcile_interrupted(self.root)

    def start(self, attempt_id: str) -> None:
        with self._lock:
            if attempt_id in self._active:
                return
            self._active.add(attempt_id)
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
            except Exception:  # noqa: BLE001
                # run() records execution errors under its file lock. An unreadable
                # store cannot be repaired here, and must not be overwritten unlocked.
                pass
            finally:
                with self._lock:
                    self._active.discard(attempt_id)
