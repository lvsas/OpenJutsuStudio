"""Permanent deletion of a Swap job and the media it owns.

Jobs live as one JSON record plus files named after their identifier:

* ``media/<job>-source.mp4``, ``-excerpt.mp4``, ``-reference-N.png``
* ``media/h3-<job>/`` (rendered result family)
* ``media/forward-<job>/`` (continuation copy, if the far end was a Take)

Nothing here guesses a path from a browser string: only a 32-hex job id selects
files that already exist. A job whose output became the origin of a native Take
is refused unless the caller explicitly accepts breaking that lineage.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

_ID = re.compile(r'[0-9a-f]{32}\Z')
_MAX_JSON = 1 << 20
_ACTIVE = {'queued', 'running', 'submitting', 'propagating'}


class JobDeletionRefused(Exception):
    """Refused before touching the disk; the message is safe to show."""


def _unlock(path: Path) -> None:
    for root, directories, files in os.walk(path):
        for name in directories + files:
            target = os.path.join(root, name)
            try:
                info = os.lstat(target)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                continue
            os.chmod(target, info.st_mode | stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
    try:
        info = os.lstat(path)
        os.chmod(path, info.st_mode | stat.S_IWUSR | stat.S_IRUSR)
    except FileNotFoundError:
        pass


def _size(path: Path) -> int:
    if path.is_file() and not path.is_symlink():
        try:
            return os.lstat(path).st_size
        except OSError:
            return 0
    total = 0
    for root, _directories, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def _trim(path: Path) -> None:
    if path.is_symlink():
        return
    if path.is_dir():
        _unlock(path)
        import shutil
        shutil.rmtree(path)
    elif path.exists():
        _unlock(path.parent)
        path.unlink()


def _takes_referencing(work: Path, job_id: str) -> list[str]:
    store = work / 'timeline' / 'continuable-takes'
    if not store.is_dir():
        return []
    found = []
    for directory in sorted(store.iterdir()):
        capsule = directory / 'capsule.json'
        if not directory.is_dir() or capsule.is_symlink() or not capsule.is_file():
            continue
        try:
            if capsule.stat().st_size > _MAX_JSON:
                continue
            body = json.loads(capsule.read_text())
        except (OSError, ValueError):
            continue
        origin = body.get('origin') if isinstance(body, dict) else None
        if isinstance(origin, dict) and origin.get('source_job') == job_id:
            found.append(directory.name)
    return found


def delete_job(work: str | Path, job_id: str, *, break_lineage: bool = False) -> dict:
    if not isinstance(job_id, str) or not _ID.match(job_id):
        raise JobDeletionRefused('Unknown Swap.')
    root = Path(work).resolve()
    record = root / 'jobs' / (job_id + '.json')
    if record.is_symlink() or not record.is_file():
        raise JobDeletionRefused('Unknown Swap.')
    try:
        body = json.loads(record.read_text()) if record.stat().st_size <= _MAX_JSON else {}
    except (OSError, ValueError):
        body = {}
    if str(body.get('status', '')).lower() in _ACTIVE:
        raise JobDeletionRefused('This Swap is still running. Wait for it to finish.')
    takes = _takes_referencing(root, job_id)
    if takes and not break_lineage:
        raise JobDeletionRefused(
            f'This Swap is the origin of {len(takes)} saved Take'
            f'{"s" if len(takes) != 1 else ""}. Delete the Take first, '
            'or confirm deleting the Swap and breaking that lineage.')
    media = root / 'media'
    targets = sorted(media.glob(job_id + '-*')) + [media / ('h3-' + job_id), media / ('forward-' + job_id)]
    freed = sum(_size(path) for path in targets if path.exists())
    for path in targets:
        if path.exists():
            _trim(path)
    freed += _size(record)
    _trim(record)
    return {'deleted': job_id, 'bytes': freed, 'takes_orphaned': takes if break_lineage else []}
