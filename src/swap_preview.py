"""Disposable CPU JPEGs from already-downloaded, validated Swap result files.

Call only after the original result endpoint validates job availability/access.
No SDK, ComfyUI, native-family registry or original artifact is modified.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

from continuable_take import (_directory, _open_file, _publish_directory,
                              _read_json, _write_json)

_VERSION = 'swap-poster-jpeg-v1'
_SLOTS = threading.BoundedSemaphore(2)
_MAX_JPEG = 512 * 1024


class PreviewUnavailable(RuntimeError):
    """Public, path-free failure (including saturation)."""


def _identity(stream):
    stat = os.fstat(stream.fileno())
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def _jpeg_digest(path):
    with _open_file(path) as stream:
        data = stream.read(_MAX_JPEG + 1)
    if (not 4 < len(data) <= _MAX_JPEG or not data.startswith(b'\xff\xd8')
            or not data.endswith(b'\xff\xd9')):
        raise ValueError('Invalid cached JPEG')
    return hashlib.sha256(data).hexdigest()


def prepare_poster(work: Path, result: Path) -> Path:
    """Bounded, atomic cache keyed by source identity/stat and encoding policy.

    The original result is immutable by contract. ctime + inode also invalidate
    replacements that preserve size/mtime. Keep its descriptor open throughout
    encoding and refuse a source mutation before publication.
    """
    # A lazy-image burst must wait for a bounded worker, not lose every card after the first two.
    if not _SLOTS.acquire(timeout=20):
        raise PreviewUnavailable('Poster service is busy. Try again shortly.')
    try:
        return _prepare(work, Path(result).absolute())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise PreviewUnavailable('The Swap poster is not available.') from exc
    finally:
        _SLOTS.release()


def _prepare(work, result):
    with _open_file(result) as source:
        binding = {'policy': _VERSION, 'source_stat': _identity(source),
                   'source_path_sha256': hashlib.sha256(os.fsencode(result)).hexdigest()}
        key = hashlib.sha256(repr(binding).encode()).hexdigest()
        root = _directory(Path(work).absolute() / 'timeline' / 'previews' / _VERSION, create=True)
        destination = root / key
        if not os.path.lexists(destination):
            staging = Path(tempfile.mkdtemp(prefix='.' + key, suffix='.part', dir=root))
            try:
                output = staging / 'poster.jpg'
                # Open descriptor pins the validated local download, even if its
                # directory entry changes. mov disables external media inputs.
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error',
                    '-protocol_whitelist', 'file', '-f', 'mov', '-enable_drefs', '0',
                    '-use_absolute_path', '0', '-threads', '1',
                    '-i', f'/proc/self/fd/{source.fileno()}',
                    '-map', '0:v:0', '-frames:v', '1', '-an', '-sn', '-dn',
                    '-vf', 'scale=320:320:force_original_aspect_ratio=decrease',
                    '-filter_threads', '1', '-map_metadata', '-1', '-map_chapters', '-1',
                    '-threads', '1', '-q:v', '4', str(output)],
                    pass_fds=(source.fileno(),), stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, check=True, timeout=20)
                if _identity(source) != binding['source_stat']:
                    raise ValueError('Source changed while preparing poster')
                _write_json(staging / 'poster.json', {**binding, 'sha256': _jpeg_digest(output)})
                try:
                    _publish_directory(staging, destination)
                except FileExistsError:
                    pass  # Another process atomically published this same key.
            finally:
                if staging.exists():
                    shutil.rmtree(staging)  # Only our own private staging fixture.
        _directory(destination)
        metadata = _read_json(destination / 'poster.json')
        output = destination / 'poster.jpg'
        if (not isinstance(metadata, dict)
                or metadata != {**binding, 'sha256': _jpeg_digest(output)}
                or _identity(source) != binding['source_stat']):
            raise ValueError('Poster cache integrity mismatch')
        return output
