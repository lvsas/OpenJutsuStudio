"""Metadata-stripped previews; never mutate or substitute the native H3 family.

Stream-copy the primary video/audio without an edit or encode. This disposable,
private cache is NOT an exported complete Take and NOT its native video hash.
Use only immediately after get_validated_family on the same trusted host.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

# Share the domain's NOFOLLOW, bounded JSON and no-clobber filesystem boundary.
from continuable_take import (_directory, _open_file, _publish_directory,
                              _read_json, _write_json, ValidatedTakeFamily)
from media_probe import probe_mp4

_LOCK = threading.Lock()
_VERSION = 'strip-container-stream-metadata-v1'


class PreviewUnavailable(RuntimeError):
    pass


def _hash(path):
    with _open_file(path) as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _cached(folder, binding):
    _directory(folder)
    document = _read_json(folder / 'preview.json')
    if (not isinstance(document, dict) or set(document) != {*binding, 'sha256', 'size_bytes'}
            or any(document[key] != value for key, value in binding.items())):
        raise ValueError('Preview source binding mismatch')
    path = folder / 'preview.mp4'
    with _open_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if not size or size != document['size_bytes'] or digest != document['sha256']:
        raise ValueError('Preview cache integrity mismatch')
    return path


def prepare_poster(work: Path, family: ValidatedTakeFamily) -> Path:
    """Small cached JPEG bound to a validated native capsule, never a video fallback."""
    record = family.record
    binding = {'capsule_sha256': record.capsule_sha256, 'policy': 'poster-jpeg-v1'}
    with _LOCK:
        root = _directory(Path(work).absolute() / 'timeline' / 'previews' / 'poster-jpeg-v1', create=True)
        destination = root / (record.take_id + '-' + record.capsule_sha256)
        if not os.path.lexists(destination):
            staging = Path(tempfile.mkdtemp(prefix='.' + record.take_id, suffix='.part', dir=root))
            try:
                output = staging / 'poster.jpg'
                try:
                    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error',
                        '-protocol_whitelist', 'file', '-f', 'mov', '-enable_drefs', '0',
                        '-use_absolute_path', '0', '-i', str(family.video),
                        '-map', '0:v:0', '-frames:v', '1', '-an',
                        '-vf', 'scale=320:320:force_original_aspect_ratio=decrease',
                        '-map_metadata', '-1', '-threads', '1', '-q:v', '4', str(output)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=30)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise PreviewUnavailable('Could not prepare take poster') from exc
                _write_json(staging / 'poster.json', {**binding, 'sha256': _hash(output)})
                try:
                    _publish_directory(staging, destination)
                except FileExistsError:
                    pass
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        _directory(destination)
        metadata = _read_json(destination / 'poster.json')
        path = destination / 'poster.jpg'
        if (any(metadata.get(key) != value for key, value in binding.items())
                or metadata.get('sha256') != _hash(path)):
            raise ValueError('Poster cache integrity mismatch')
        return path


def prepare_preview(work: Path, family: ValidatedTakeFamily) -> Path:
    """Return an exact-source-bound derivative, never a raw native MP4 fallback."""
    record = family.record
    manifest = record.to_manifest()
    binding = {'policy': _VERSION, 'capsule_sha256': record.capsule_sha256,
               'source_video_sha256': manifest['family']['assets']['video']['sha256']}
    with _LOCK:
        root = _directory(Path(work).absolute() / 'timeline' / 'previews' / _VERSION, create=True)
        destination = root / (record.take_id + '-' + record.capsule_sha256)
        if os.path.lexists(destination):
            return _cached(destination, binding)
        staging = Path(tempfile.mkdtemp(prefix='.' + record.take_id + '.', suffix='.part', dir=root))
        try:
            output = staging / 'preview.mp4'
            try:
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error',
                    '-protocol_whitelist', 'file', '-f', 'mov', '-enable_drefs', '0',
                    '-use_absolute_path', '0', '-i', str(family.video),
                    '-map', '0:v:0', '-map', '0:a:0?', '-map_metadata', '-1',
                    '-map_metadata:s', '-1', '-map_chapters', '-1',
                    '-c', 'copy', '-threads', '1', '-movflags', '+faststart', str(output)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=45)
                geometry = probe_mp4(output)
            except (OSError, subprocess.SubprocessError) as exc:
                raise PreviewUnavailable('Could not prepare metadata-stripped preview') from exc
            context = manifest['family']['context']
            if (any(geometry[key] != context[key] for key in ('width', 'height'))
                    or geometry['frames'] != context['delivered_frames']
                    or abs(geometry['fps'] - context['fps']) > 0.000001):
                raise ValueError('Preview changed delivered geometry or frame count')
            _write_json(staging / 'preview.json', {**binding, 'sha256': _hash(output),
                'size_bytes': output.stat().st_size})
            for path in staging.iterdir():
                path.chmod(0o400)
            staging.chmod(0o500)
            try:
                _publish_directory(staging, destination)
            except FileExistsError:
                # A different process may have published this exact immutable source.
                pass
        finally:
            if staging.exists():
                staging.chmod(0o700)
                shutil.rmtree(staging)
        return _cached(destination, binding)
