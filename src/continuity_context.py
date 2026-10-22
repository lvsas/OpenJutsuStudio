"""Ordered references for the next generation, never a mutation of a Take.

A missing context inherits; a published context (including []) overrides. Images
are private copies with stable names; their list positions define <Picture N>.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from threading import RLock
import uuid

_ID = re.compile(r'[0-9a-f]{32}\Z')
_NAME = re.compile(r'reference-[0-9a-f]+\.(png|jpg|jpeg|webp)\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
MAX_BYTES = 32 * 1024 * 1024
MAX_CONTEXT_BYTES = 16 * 1024 * 1024
_FOLDER = 'continuity-contexts'
_LOCK = RLock()


def _folder(work: str | Path, take_id: str) -> Path:
    if not isinstance(take_id, str) or not _ID.fullmatch(take_id):
        raise ValueError('A take identifier is required')
    folder = Path(work) / 'timeline' / _FOLDER / take_id
    if folder.is_symlink():
        raise ValueError('The generation context must not be a symlink')
    return folder


def _manifest(folder: Path) -> dict:
    path = folder / 'context.json'
    if path.is_symlink():
        raise ValueError('The generation context must not be a symlink')
    if not path.exists():
        return {'references': []}
    with path.open('rb') as stream:
        raw = stream.read(MAX_CONTEXT_BYTES + 1)
    if len(raw) > MAX_CONTEXT_BYTES:
        raise ValueError('The generation context exceeds the JSON byte limit')
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get('references'), list):
        raise ValueError('The generation context is unreadable')
    return value


def _write(folder: Path, value: dict) -> None:
    raw = json.dumps(value, sort_keys=True).encode()
    if len(raw) > MAX_CONTEXT_BYTES:
        raise ValueError('The generation context exceeds the JSON byte limit')
    staging = folder / f'.context.{uuid.uuid4().hex}.tmp'
    try:
        staging.write_bytes(raw)
        staging.replace(folder / 'context.json')
    finally:
        staging.unlink(missing_ok=True)


def _read_image(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError('The generation context reference is missing or unsafe')
    with path.open('rb') as stream:
        payload = stream.read(MAX_BYTES + 1)
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError('A reference image is empty or larger than the accepted limit')
    return payload


def _paths(folder: Path, manifest: dict) -> list[Path]:
    paths = []
    for item in manifest['references']:
        if (not isinstance(item, dict) or not isinstance(item.get('filename'), str)
                or not _NAME.fullmatch(item['filename'])
                or not isinstance(item.get('sha256'), str) or not _SHA.fullmatch(item['sha256'])):
            raise ValueError('The generation context reference is unreadable')
        path = folder / item['filename']
        if hashlib.sha256(_read_image(path)).hexdigest() != item['sha256']:
            raise ValueError('The generation context reference no longer matches its hash')
        paths.append(path)
    return paths


def has_context(work: str | Path, take_id: str) -> bool:
    """Manifest existence, not reference count, determines an explicit override."""
    with _LOCK:
        path = _folder(work, take_id) / 'context.json'
        return path.exists() or path.is_symlink()


def context_references(work: str | Path, take_id: str) -> list[Path]:
    """Read and hash-verify every prepared reference, in order."""
    with _LOCK:
        folder = _folder(work, take_id)
        return _paths(folder, _manifest(folder))


def context_manifest(work: str | Path, take_id: str) -> dict:
    with _LOCK:
        folder = _folder(work, take_id)
        value = _manifest(folder)
        _paths(folder, value)
        return value


def _store_image(folder: Path, payload: bytes, suffix: str) -> dict:
    if not isinstance(payload, bytes) or not payload:
        raise ValueError('An empty reference is not useful')
    if len(payload) > MAX_BYTES:
        raise ValueError('A reference image is larger than the accepted limit')
    suffix = suffix.lower() if isinstance(suffix, str) else ''
    if suffix not in _SUFFIXES:
        raise ValueError('A reference must be a PNG, JPEG or WebP image')
    folder.mkdir(parents=True, exist_ok=True)
    name = f'reference-{uuid.uuid4().hex}{suffix}'
    with (folder / name).open('xb') as stream:
        stream.write(payload)
    return {'filename': name, 'sha256': hashlib.sha256(payload).hexdigest()}


def seed_context(work: str | Path, take_id: str, inherited) -> dict:
    """Copy all inherited images once; never resolve origin for a prepared set.

    ``inherited`` is lazy so existing contexts do not read historical sources.
    Only the caller decides which missing-history error may mean an empty set.
    """
    with _LOCK:
        if has_context(work, take_id):
            return context_manifest(work, take_id)
        folder = _folder(work, take_id)
        sources = list(inherited())
        manifest = {'references': []}
        try:
            for source in sources:
                source = Path(source)
                manifest['references'].append(_store_image(folder, _read_image(source), source.suffix))
            folder.mkdir(parents=True, exist_ok=True)
            _write(folder, manifest)
        except Exception:
            for item in manifest['references']:
                (folder / item['filename']).unlink(missing_ok=True)
            raise
        return manifest


def _edit(work, take_id, *, payload: bytes = b'', suffix: str = '',
          position: int | None = None, remove=False):
    with _LOCK:
        folder = _folder(work, take_id)
        manifest = context_manifest(work, take_id)
        items = manifest['references']
        if (remove and position is None
                or position is not None and not 1 <= position <= len(items)):
            raise ValueError('Unknown reference')
        dropped = items[position - 1] if position is not None else None
        added = None if remove else _store_image(folder, payload, suffix)
        if remove:
            assert position is not None
            items.pop(position - 1)
        elif position is None:
            items.append(added)
        else:
            items[position - 1] = added
        try:
            _write(folder, manifest)
        except Exception:
            if added:
                (folder / added['filename']).unlink(missing_ok=True)
            raise
        if dropped:
            (folder / dropped['filename']).unlink(missing_ok=True)
        return manifest


def add_reference(work: str | Path, take_id: str, payload: bytes, suffix: str) -> dict:
    """Append an image without a fixed reference-count cap."""
    return _edit(work, take_id, payload=payload, suffix=suffix)


def remove_reference(work: str | Path, take_id: str, position: int) -> dict:
    """Drop one list position; stable filenames avoid remove/add collisions."""
    return _edit(work, take_id, position=position, remove=True)


def replace_reference(work: str | Path, take_id: str, position: int,
                      payload: bytes, suffix: str) -> dict:
    """Replace one image at its existing <Picture N> position."""
    return _edit(work, take_id, position=position, payload=payload, suffix=suffix)
