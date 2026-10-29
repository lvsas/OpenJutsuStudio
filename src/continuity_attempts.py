"""Bounded seed attempts: one frozen request, several candidates, one choice.

A hunt is not a new pipeline. It refines the direction once, then submits the same
frozen request with different seeds, sequentially, on the single GPU worker. Each
candidate is an ordinary native operation with its own durable record. Completed
candidates are never resubmitted; interrupted submissions require explicit recovery.
"""
from __future__ import annotations

import json
import copy
import os
import re
import threading
import uuid
import fcntl
from contextlib import contextmanager
from pathlib import Path
from h3_source_audio import validate_audio_context

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


def _validate_anchors(take_id, *, mode, second_take_id):
    if mode == 'root':
        if take_id is not None or second_take_id is not None:
            raise AttemptError('Root generation has no parent takes.')
        return
    if not isinstance(mode, str) or mode not in ('forward', 'prepend', 'bridge'):
        raise AttemptError('Choose forward, prepend or bridge generation.')
    if mode == 'bridge':
        _identifier(second_take_id, 'second take')
        if second_take_id == take_id:
            raise AttemptError('Bridge generation requires two distinct takes.')
    elif second_take_id is not None:
        raise AttemptError('A second take is only allowed for bridge generation.')


def validate_reference_ids(ids):
    if not isinstance(ids, list) or not ids:
        raise AttemptError('At least one generation reference is required.')
    for identifier in ids:
        _identifier(identifier, 'reference')
    return list(ids)


def validate_root_context(root_context):
    """The entire browser-controllable root intent, not arbitrary graph JSON."""
    if not isinstance(root_context, dict) or set(root_context) != {'reference_ids', 'width', 'height'}:
        raise AttemptError('Root generation requires explicit references and picture size.')
    ids = root_context['reference_ids']
    if not isinstance(ids, list) or not ids:
        raise AttemptError('At least one root reference is required.')
    for identifier in ids:
        _identifier(identifier, 'reference')
    for field in ('width', 'height'):
        value = root_context[field]
        if type(value) is not int or not 32 <= value <= 2048 or value % 32:
            raise AttemptError('Root picture size must be 32-aligned integers between 32 and 2048.')
    return copy.deepcopy(root_context)


def _validate_context(mode, root_context):
    if mode == 'root':
        validate_root_context(root_context)
    elif root_context is not None:
        raise AttemptError('Root context is only allowed for root generation.')


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
    try:
        _validate_anchors(value['take_id'], mode=value.get('mode', 'forward'),
                          second_take_id=value.get('second_take_id'))
        _validate_context(value.get('mode', 'forward'), value.get('root_context'))
        if value.get('frozen_audio_context') is not None:
            try:
                validate_audio_context(value['frozen_audio_context'])
            except ValueError:
                raise AttemptError('The saved soundtrack context is invalid.') from None
            if value.get('mode', 'forward') != 'forward':
                raise AttemptError('Only Extend can contain an original soundtrack context.')
        if value.get('project_id') is not None:
            _identifier(value['project_id'], 'project')
    except AttemptError:
        raise AttemptError('The attempt record cannot be read.') from None
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


def root_by_request(root, request_id) -> dict:
    """Read-only recovery scoped strictly to parentless root records."""
    _identifier(request_id, 'request')
    for attempt in _records(root):
        if (attempt.get('mode') == 'root' and attempt['take_id'] is None
                and attempt.get('request_id') == request_id):
            return attempt
    raise AttemptNotFound('Attempt not found.')


def list_for_take(root, take_id) -> list[dict]:
    """Include legacy attempts without a request_id, most recently updated first."""
    _identifier(take_id, 'take')
    return [attempt for attempt in _records(root) if attempt['take_id'] == take_id]


def _validate(*, take_id, prompt, raw_frames, seeds, request_id, mode, second_take_id,
              root_context=None):
    if mode != 'root':
        _identifier(take_id, 'take')
    _validate_anchors(take_id, mode=mode, second_take_id=second_take_id)
    _validate_context(mode, root_context)
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
        raise AttemptError('Seeds must be distinct whole numbers from 0 to 2^64-1 (uint64).')
    return seeds


def create(root, *, take_id: str | None, prompt: str, raw_frames: int, seeds,
           request_id: str | None = None, mode: str = 'forward',
           second_take_id: str | None = None, root_context=None) -> dict:
    """Legacy internal callers may omit the request identity."""
    attempt, _ = create_or_get(root, take_id=take_id, prompt=prompt,
                               raw_frames=raw_frames, seeds=seeds, request_id=request_id,
                               mode=mode, second_take_id=second_take_id, root_context=root_context)
    return attempt


def create_or_get(root, *, take_id: str | None, prompt: str, raw_frames: int, seeds,
                  request_id: str | None = None, mode: str = 'forward',
                  second_take_id: str | None = None, root_context=None, reference_ids=None, frozen_reference_paths=None, project_id=None, frozen_audio_context=None) -> tuple[dict, bool]:
    """Return (record, created); persist identity and intent in one locked write.

    Only the caller receiving created=True may queue work. A crash between this
    write and queueing leaves a recoverable pending record, not an automatic retry.
    """
    seeds = _validate(take_id=take_id, prompt=prompt, raw_frames=raw_frames,
                      seeds=seeds, request_id=request_id, mode=mode, second_take_id=second_take_id,
                      root_context=root_context)
    if project_id is not None:
        _identifier(project_id, "project")
    root_context = copy.deepcopy(root_context)
    if frozen_audio_context is not None:
        if mode != 'forward':
            raise AttemptError('Original soundtrack continuation requires Extend.')
        frozen_audio_context = validate_audio_context(frozen_audio_context)
    if reference_ids is not None:
        reference_ids = validate_reference_ids(reference_ids)
        if mode == 'root':
            raise AttemptError('Root references belong to its root context.')
    store = Path(root).joinpath(*ROOT)
    store.mkdir(parents=True, exist_ok=True)
    with _file_lock(store / '.create.lock'):
        if request_id is not None:
            for existing in _records(root):
                if existing.get('request_id') != request_id:
                    continue
                intent = (existing['take_id'], existing['prompt'], existing['raw_frames'],
                          [c['seed'] for c in existing['candidates']],
                          existing.get('mode', 'forward'), existing.get('second_take_id'),
                          existing.get('root_context'), existing.get('reference_ids'), existing.get('project_id'))
                if intent != (take_id, prompt, raw_frames, seeds, mode, second_take_id, root_context, reference_ids, project_id):
                    raise AttemptConflict('This request identifier already has a different frozen payload.')
                return existing, False
        attempt = {'version': 1, 'attempt_id': uuid.uuid4().hex, 'take_id': take_id,
                   'prompt': prompt, 'raw_frames': raw_frames, 'status': _STATUS_PENDING,
                   'refined_prompt': None, 'error': None,
                   'candidates': [{'operation_id': uuid.uuid4().hex, 'seed': seed,
                                   'status': _STATUS_PENDING, 'take_id': None, 'error': None}
                                  for seed in seeds]}
        attempt['frozen_audio_context'] = copy.deepcopy(frozen_audio_context)
        if project_id is not None:
            attempt['project_id'] = project_id
        if request_id is not None:
            attempt['request_id'] = request_id
        if mode == 'root':
            attempt.update(mode='root', root_context=root_context)
        elif mode != 'forward':
            attempt.update(mode=mode, second_take_id=second_take_id)
        if reference_ids is not None:
            attempt['reference_ids'] = list(reference_ids)
        if frozen_reference_paths is not None:
            if not isinstance(frozen_reference_paths, (list, tuple)) or not frozen_reference_paths or any(
                    not isinstance(path, str) or not path for path in frozen_reference_paths):
                raise AttemptError('Frozen references must be nonempty trusted server paths.')
            attempt['frozen_reference_paths'] = list(frozen_reference_paths)
        _atomic(_folder(root, attempt['attempt_id']) / 'attempt.json', attempt)
        return attempt, True


def _public_error(error):
    if error is None:
        return None
    messages = {
        'No candidate completed.',
        'A candidate outcome is unknown; explicit operation recovery is required.',
        'The server interrupted preparation or queued work; nothing was automatically restarted.',
        'Submission outcome unknown; not resubmitted.',
        'Not started before the server interruption.',
    }
    return error if isinstance(error, str) and error in messages else (
        'This generation step could not finish. Check the saved attempt before starting another.')


def _public_candidate(candidate, attempt):
    # Older preparation failures left pending rows in a terminal attempt. Such a
    # row was never started (running is checkpointed before submit). Normalize
    # the read-only projection, not its durable record or an uncertain outcome.
    unstarted = attempt['status'] == _STATUS_FAILED and candidate['status'] == _STATUS_PENDING
    take_id = candidate['take_id']
    return {'seed': candidate['seed'],
            'status': _STATUS_FAILED if unstarted else candidate['status'],
            'take_id': take_id,
            'error': _public_error(attempt['error'] if unstarted else candidate['error']),
            'url': f'/api/continuity/takes/{take_id}' if take_id else None}


def _fail_preparation(attempt, error):
    attempt.update(status=_STATUS_FAILED, error=error)
    for candidate in attempt['candidates']:
        if candidate['status'] == _STATUS_PENDING:
            candidate.update(status=_STATUS_FAILED, error=error)


def public(attempt: dict) -> dict:
    result = {'attempt_id': attempt['attempt_id'], 'take_id': attempt['take_id'],
            'status': attempt['status'], 'error': _public_error(attempt['error']),
            'candidates': [_public_candidate(c, attempt) for c in attempt['candidates']]}
    if attempt.get('project_id') is not None:
        result['project_id'] = attempt['project_id']
    if attempt.get('mode') == 'root':
        result['mode'] = 'root'
    elif attempt.get('mode', 'forward') != 'forward':
        result.update(mode=attempt['mode'], second_take_id=attempt.get('second_take_id'))
    return result


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
    # Forward retains the exact historical positional callback contract.
    anchors = ({} if attempt.get('mode', 'forward') == 'forward' else
               {'mode': attempt['mode'], 'second_take_id': attempt.get('second_take_id')})
    if attempt.get('mode') == 'root':
        anchors = {'mode': 'root', 'root_context': attempt['root_context']}
    if attempt.get('reference_ids') is not None:
        anchors['reference_ids'] = validate_reference_ids(attempt['reference_ids'])
    if attempt.get('frozen_reference_paths') is not None:
        anchors['reference_paths'] = list(attempt['frozen_reference_paths'])
    if attempt.get('frozen_audio_context') is not None:
        anchors['audio_context'] = validate_audio_context(attempt['frozen_audio_context'])
    if any(c['status'] in ('running', 'unknown') for c in attempt['candidates']):
        if any(c['status'] == 'running' for c in attempt['candidates']):
            return _mark_interrupted(root, attempt_id)
        return attempt
    if all(c['status'] == _STATUS_DONE for c in attempt['candidates']):
        return attempt
    refined = attempt.get('refined_prompt')
    if refined is None:
        try:
            refine_options = copy.deepcopy(anchors)
            if 'audio_context' in refine_options:
                refine_options['raw_frames'] = attempt['raw_frames']
            refined = refine(attempt['prompt'], attempt['take_id'], **refine_options)
        except Exception as error:  # noqa: BLE001
            return _update(root, attempt_id, lambda a: _fail_preparation(
                a, f'The direction could not be prepared: {error}'[:400]))
    _update(root, attempt_id, lambda a: a.update(
        refined_prompt=refined, status=_STATUS_RUNNING, error=None))
    for index, candidate in enumerate(load(root, attempt_id)['candidates']):
        if candidate['status'] == _STATUS_DONE:
            continue
        _update(root, attempt_id, lambda a, i=index: a['candidates'][i].update(
            status=_STATUS_RUNNING, error=None))
        try:
            take_id = submit(candidate['operation_id'], refined, candidate['seed'],
                             attempt['raw_frames'], attempt['take_id'], **copy.deepcopy(anchors))
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
