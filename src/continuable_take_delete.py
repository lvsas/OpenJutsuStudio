"""Permanent deletion of native Takes, with explicit guards.

The store is immutable by design: every artifact is written read-only so a later
run cannot rewrite evidence. That is why nothing could ever be removed from the
app. Deletion therefore has to be an explicit, guarded operation that

* refuses while a Take still has children (a cascade must be asked for),
* refuses while a generation is in flight for that Take,
* unlocks only the directory tree it is about to remove,
* removes the duplicated ``media/forward-<id>`` copy when it belongs to the Take.

No path is ever taken from the browser: only a 32-hex Take identifier selects a
directory that already exists under the store.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

_ID = __import__('re').compile(r'[0-9a-f]{32}\Z')
_MAX_CAPSULE = 1 << 20
_ACTIVE = {'pending', 'queued', 'running', 'submitting'}


class TakeDeletionRefused(Exception):
    """The request is understood and refused; the message is safe to show."""


def _store(work: str | Path) -> Path:
    return Path(work).resolve() / 'timeline' / 'continuable-takes'


def _capsule_of(directory: Path) -> dict:
    path = directory / 'capsule.json'
    try:
        if path.is_symlink() or not path.is_file():
            return {}
        if path.stat().st_size > _MAX_CAPSULE:
            return {}
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _parent_of(directory: Path) -> str | None:
    lineage = _capsule_of(directory).get('lineage')
    if not isinstance(lineage, dict):
        return None
    parent = lineage.get('parent_id')
    return parent if isinstance(parent, str) and _ID.match(parent) else None


def _in_flight(work: str | Path, take_id: str) -> bool:
    """Any recorded attempt that already accepted work for this Take."""
    for path in Path(work).resolve().rglob('attempt.json'):
        try:
            if path.stat().st_size > _MAX_CAPSULE or path.is_symlink():
                continue
            body = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(body, dict):
            continue
        if str(body.get('status', '')).lower() not in _ACTIVE:
            continue
        if body.get('take_id') == take_id or body.get('parent_take_id') == take_id:
            return True
        for candidate in body.get('candidates') or ():
            if isinstance(candidate, dict) and str(candidate.get('status', '')).lower() in _ACTIVE:
                return True
    return False


def _unlock(path: Path) -> None:
    """Immutable artifacts are read-only; restore write bits before unlinking."""
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
    info = os.lstat(path)
    os.chmod(path, info.st_mode | stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)


def _size(path: Path) -> int:
    total = 0
    for root, _directories, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except FileNotFoundError:
                pass
    return total


def _remove_one(work: Path, store: Path, take_id: str) -> int:
    directory = store / take_id
    if directory.is_symlink():
        raise TakeDeletionRefused('That Take cannot be deleted safely.')
    if directory.resolve().parent != store.resolve():
        raise TakeDeletionRefused('That Take cannot be deleted safely.')
    size = _size(directory)
    _unlock(directory)
    shutil.rmtree(directory)
    copy = Path(work).resolve() / 'media' / ('forward-' + take_id)
    if copy.is_dir() and not copy.is_symlink() and copy.resolve().parent == (Path(work).resolve() / 'media').resolve():
        size += _size(copy)
        _unlock(copy)
        shutil.rmtree(copy)
    return size


def delete_take(work: str | Path, take_id: str, *, cascade: bool = False) -> dict:
    """Delete one native Take (and, on request, its descendants).

    Returns the identifiers actually removed and the bytes reclaimed. Raises
    ``TakeDeletionRefused`` with a user-safe message for every refusal, so the
    HTTP layer never has to translate an internal exception.
    """
    if not isinstance(take_id, str) or not _ID.match(take_id):
        raise TakeDeletionRefused('Unknown Take.')
    store = _store(work)
    if not store.is_dir():
        raise TakeDeletionRefused('Unknown Take.')
    if not (store / take_id).is_dir():
        raise TakeDeletionRefused('Unknown Take.')
    if _in_flight(work, take_id):
        raise TakeDeletionRefused('This Take is still being generated. Wait for it to finish.')
    takes = {path.name for path in store.iterdir() if path.is_dir() and _ID.match(path.name)}
    children: dict[str, list[str]] = {}
    for name in takes:
        parent = _parent_of(store / name)
        if parent:
            children.setdefault(parent, []).append(name)
    if take_id in children and not cascade:
        branch: list[str] = []
        seen_branch: set[str] = set()

        def walk(name: str) -> None:
            if name in seen_branch:
                return
            seen_branch.add(name)
            for child in children.get(name, ()):
                walk(child)
                branch.append(child)

        walk(take_id)
        count = len(branch)
        raise TakeDeletionRefused(
            f'This Take has {count} later Take{"s" if count != 1 else ""} in its branch. '
            'Delete them first, or confirm deleting the whole branch.')
    order: list[str] = []
    seen: set[str] = set()

    def collect(name: str) -> None:
        if name in seen or name not in takes:
            return
        seen.add(name)
        for child in sorted(children.get(name, ())):
            collect(child)
        order.append(name)

    collect(take_id)
    for name in order:
        if _in_flight(work, name):
            raise TakeDeletionRefused('One Take in this branch is still being generated. Wait for it to finish.')
    freed = 0
    for name in order:
        freed += _remove_one(Path(work), store, name)
    return {'deleted': order, 'bytes': freed}
