"""Private native-operation checkpoints around the official SDK.

Not another queue: call execute_operation on the app's existing single executor.
Only trusted server code supplies compiled graphs and target fingerprints; no
browser-facing graph/path API is provided. Unknown submit outcomes never trigger
an automatic second POST. Collection callbacks must be idempotent by operation ID.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from continuable_take import _directory

_ID = re.compile(r'[0-9a-f]{32}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_LOCK = threading.RLock()
_RUN_LOCK = threading.Lock()
_MODES = {'swap': 0, 'root': 0, 'forward': 1, 'reverse': 1, 'bridge': 2, 'refine': 1}
_STATUSES = {'queued', 'submitting', 'waiting', 'collecting', 'done', 'uncertain', 'error'}


class OperationUncertain(RuntimeError):
    def __init__(self, operation_id, remote_job_id=None):
        self.operation_id, self.remote_job_id = operation_id, remote_job_id
        super().__init__('Native operation requires recovery; do not resubmit blindly')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _path(work_root, operation_id, *, create=False):
    if not isinstance(operation_id, str) or not _ID.fullmatch(operation_id):
        raise ValueError('Invalid native operation ID')
    folder = Path(work_root) / 'timeline' / 'continuity-operations' / operation_id
    _directory(folder, create=create)
    return folder / 'operation.json'


def _sync_dir(folder):
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path, record):
    """Private atomic checkpoint; a published record is never cleaned away."""
    payload = (_canonical(record) + '\n').encode()
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError('Native operation intent is too large')
    fd, temporary = tempfile.mkstemp(prefix='.operation-', suffix='.part', dir=path.parent)
    published = False
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        published = True
        _sync_dir(path.parent)
    except OSError as exc:
        raise OperationUncertain(record['id'], record['remote_job_id']) from exc
    finally:
        if not published:
            try:
                os.unlink(temporary)
            except OSError:
                pass  # Never mask the known operation/remote recovery identifiers.


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        import stat
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('Invalid native operation record')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Native operation intent is too large')
        record = json.loads(raw)
    finally:
        os.close(fd)
    if (record.get('version') != 1 or record.get('id') != path.parent.name
            or record.get('status') not in _STATUSES
            or record.get('intent_digest') != _digest(record.get('intent'))
            or record.get('idempotency_key') != 'opengenjutsu-native-' + path.parent.name):
        raise ValueError('Corrupt native operation checkpoint')
    return record


def create_operation(work_root, operation_id, *, mode, graph, seed, parents=(), target_fingerprint):
    """Freeze a trusted compiled graph before any SDK submit. Same ID/intent is idempotent."""
    if mode not in _MODES or not isinstance(parents, tuple) or len(parents) != _MODES[mode]:
        raise ValueError('Native operation mode/parent count mismatch')
    if any(not isinstance(p, str) or not _ID.fullmatch(p) for p in parents) or len(set(parents)) != len(parents):
        raise ValueError('Invalid native operation parent IDs')
    if (type(seed) is not int or not 0 <= seed < 2**64
            or not isinstance(target_fingerprint, str) or not _HASH.fullmatch(target_fingerprint)
            or not isinstance(graph, dict) or not graph):
        raise ValueError('Invalid native operation seed, target or compiled graph')
    intent = {'mode': mode, 'graph': copy.deepcopy(graph), 'seed': seed,
              'parents': list(parents), 'target_fingerprint': target_fingerprint}
    digest = _digest(intent)
    with _LOCK:
        path = _path(work_root, operation_id, create=True)
        if os.path.lexists(path):
            existing = _read(path)
            if existing['intent_digest'] != digest:
                raise ValueError('Native operation ID already has a different frozen intent')
            return public_operation(existing)
        record = {'version': 1, 'id': operation_id, 'intent': intent,
                  'intent_digest': digest, 'idempotency_key': 'opengenjutsu-native-' + operation_id,
                  'status': 'queued', 'remote_job_id': None, 'take_id': None,
                  'error_code': None, 'error_detail': None, 'revision': 0}
        _write(path, record)
        return public_operation(record)


def public_operation(record):
    # Never expose raw SDK errors, even from older records: details can contain
    # credentials, private paths and prompts. Only server-authored text is public.
    return {key: copy.deepcopy(record[key]) for key in
            ('id', 'status', 'take_id', 'error_code', 'revision')} | {
        'mode': record['intent']['mode'],
        'error_detail': ('The compute target rejected workflow inputs. Check the required nodes and models.'
                         if record.get('error_code') == 'target_rejected_inputs' else None)}


def get_operation(work_root, operation_id):
    with _LOCK:
        return public_operation(_read(_path(work_root, operation_id)))


def execute_operation(work_root, operation_id, client, *, target_fingerprint, collect, timeout=1800):
    """Resume by recorded remote ID, never by Cloud labels/listing or guessed output paths.

    collect(remote_job, frozen_intent, operation_id) must validate/publish the
    actual family and return its 32-hex Take ID. It may be called again after a
    collection/checkpoint failure; it must recover an already-published Take.
    """
    from comfy_sdk.exceptions import InvalidWorkflow
    from comfy_sdk.workflows import WorkflowFactory
    with _RUN_LOCK:
        path = _path(work_root, operation_id)
        record = _read(path)
        if record['intent']['target_fingerprint'] != target_fingerprint:
            raise ValueError('Native operation belongs to a different compute target')
        if record['status'] in ('done', 'error'):
            return public_operation(record)

        def checkpoint(**changes):
            record.update(changes)
            record['revision'] += 1
            with _LOCK:
                _write(path, record)

        if record['remote_job_id'] is None:
            if record['status'] != 'queued':
                raise OperationUncertain(operation_id)
            workflow = WorkflowFactory().from_json(copy.deepcopy(record['intent']['graph']))
            checkpoint(status='submitting', error_code=None)
            try:
                remote = client.submit(workflow, idempotency_key=record['idempotency_key'])
            except InvalidWorkflow:
                # A structural rejection is a definite answer, not an unknown
                # outcome: no job exists, so retrying is safe and the reason must
                # reach the operator instead of a generic collection failure.
                checkpoint(status='error', error_code='target_rejected_inputs',
                           error_detail=None)
                return public_operation(record)
            except Exception as exc:
                checkpoint(status='uncertain', error_code='submit_outcome_unknown')
                raise OperationUncertain(operation_id) from exc
            remote_id = remote.id
            if not isinstance(remote_id, str) or not remote_id or len(remote_id) > 512 or any(c in remote_id for c in '\x00\r\n'):
                checkpoint(status='uncertain', error_code='invalid_remote_identity')
                raise OperationUncertain(operation_id)
            checkpoint(status='waiting', remote_job_id=remote_id)
        else:
            remote = client.jobs.get(record['remote_job_id'])
            if remote.id != record['remote_job_id']:
                raise ValueError('SDK resumed a different native operation job')
        try:
            remote.wait(timeout=timeout)
        except TimeoutError:
            checkpoint(status='waiting', error_code='wait_timeout')
            raise
        if remote.status != 'succeeded':
            checkpoint(status='error', error_code='remote_failed')
            return public_operation(record)
        checkpoint(status='collecting', error_code=None)
        try:
            take_id = collect(remote, copy.deepcopy(record['intent']), operation_id)
            if not isinstance(take_id, str) or not _ID.fullmatch(take_id):
                raise ValueError('Collector did not return a validated Take ID')
        except Exception:
            checkpoint(status='collecting', error_code='collection_failed')
            raise
        checkpoint(status='done', take_id=take_id)
        return public_operation(record)
