"""References for the *next* generation, without rewriting the take.

A take keeps what it was generated with. When the operator adds a character or a
set that was not in the previous video, that is a new generation context attached
to the take, never a mutation of its capsule. The forward reads the context first,
then the take's own identity, then its origin job.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import uuid

_ID = re.compile(r'[0-9a-f]{32}\Z')
_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
MAX_BYTES = 32 * 1024 * 1024
MAX_REFERENCES = 16
_FOLDER = 'continuity-contexts'


def _folder(work: str | Path, take_id: str) -> Path:
    if not isinstance(take_id, str) or not _ID.fullmatch(take_id):
        raise ValueError('A take identifier is required')
    return Path(work) / 'timeline' / _FOLDER / take_id


def _manifest(folder: Path) -> dict:
    path = folder / 'context.json'
    if not path.is_file():
        return {'references': []}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get('references'), list):
        raise ValueError('The generation context is unreadable')
    return value


def _write(folder: Path, value: dict) -> None:
    staging = folder / f'.context.{uuid.uuid4().hex}.tmp'
    staging.write_text(json.dumps(value, sort_keys=True))
    staging.replace(folder / 'context.json')


def context_references(work: str | Path, take_id: str) -> list[Path]:
    """The ordered references prepared for the next generation, if any."""
    folder = _folder(work, take_id)
    if not folder.is_dir():
        return []
    return [folder / item['filename'] for item in _manifest(folder)['references']]


def context_manifest(work: str | Path, take_id: str) -> dict:
    folder = _folder(work, take_id)
    return _manifest(folder) if folder.is_dir() else {'references': []}


def add_reference(work: str | Path, take_id: str, payload: bytes, suffix: str) -> dict:
    """Append one image. Order is meaningful: it becomes <Picture N>."""
    if not isinstance(payload, bytes) or not payload:
        raise ValueError('An empty reference is not useful')
    if len(payload) > MAX_BYTES:
        raise ValueError('A reference image is larger than the accepted limit')
    suffix = suffix.lower() if isinstance(suffix, str) else ''
    if suffix not in _SUFFIXES:
        raise ValueError('A reference must be a PNG, JPEG or WebP image')
    folder = _folder(work, take_id)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(folder)
    if len(manifest['references']) >= MAX_REFERENCES:
        raise ValueError(f'A context holds at most {MAX_REFERENCES} references')
    position = len(manifest['references']) + 1
    name = f'reference-{position}{suffix}'
    staging = folder / f'.{name}.{uuid.uuid4().hex}.tmp'
    staging.write_bytes(payload)
    staging.replace(folder / name)
    manifest['references'].append({
        'filename': name,
        'sha256': hashlib.sha256(payload).hexdigest(),
    })
    _write(folder, manifest)
    return manifest


def remove_reference(work: str | Path, take_id: str, position: int) -> dict:
    """Drop one reference and renumber the rest, so <Picture N> stays contiguous."""
    folder = _folder(work, take_id)
    manifest = _manifest(folder)
    items = manifest['references']
    if not 1 <= position <= len(items):
        raise ValueError('Unknown reference')
    dropped = items.pop(position - 1)
    (folder / dropped['filename']).unlink(missing_ok=True)
    for index, item in enumerate(items, start=1):
        current = folder / item['filename']
        wanted = f'reference-{index}{current.suffix}'
        if current.name != wanted and current.is_file():
            current.replace(folder / wanted)
            item['filename'] = wanted
    _write(folder, manifest)
    return manifest
