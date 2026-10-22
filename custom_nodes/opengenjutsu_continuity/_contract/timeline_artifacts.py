"""Read-only validation of an explicit MP4 / MCTX / COND artifact family.

A successful result proves byte identity, supported envelopes and delivered
video geometry. It does NOT certify model/runtime compatibility, numeric
conditioning semantics, visual continuity, or transport through the SDK.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

from .h3_conditioning import validate_conditioning_structure
from .media_probe import probe_mp4
from .safetensor_header import HeaderValidationError, SafetensorsHeader, read_safetensors_header

_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_INTEGER = re.compile(r'[0-9]{1,10}\Z')
# Persisted rates use bounded decimal/rational literals, never exponent notation.
_FRAME_RATE = re.compile(r'(?:[0-9]{1,6}(?:\.[0-9]{1,9})?|[0-9]{1,9}/[0-9]{1,9})\Z')
_SUFFIXES = {'video': '.mp4', 'mctx': '.mctx.safetensors', 'conditioning': '.cond.safetensors'}
_FLOAT_DTYPES = frozenset({'F16', 'BF16', 'F32', 'F64'})
# ComfyUI inserts a collision counter immediately before the final extension.
# Normalize only for role checking; always open/hash the actual supplied path.
_UPLOAD_DEDUP = re.compile(r' \([0-9]+\)(?=\.[^./]+$)')


def has_h3_role_suffix(path: str | Path, role: str) -> bool:
    """One suffix policy for native files and SDK/ComfyUI deduplicated uploads."""
    name = _UPLOAD_DEDUP.sub('', Path(path).name.lower())
    return name.endswith(_SUFFIXES[role])


class ArtifactValidationError(ValueError):
    """Stable error code and role, with no local filesystem path in the message."""

    def __init__(self, code: str, role: str, message: str):
        self.code, self.role = code, role
        super().__init__(f'{role}: {message}')


@dataclass(frozen=True, slots=True)
class ArtifactDigest:
    role: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class H3Context:
    self_id: str
    width: int
    height: int
    fps: float
    raw_frames: int
    delivered_frames: int


@dataclass(frozen=True, slots=True)
class H3ArtifactSet:
    assets: tuple[ArtifactDigest, ...]
    context: H3Context

    def to_manifest(self) -> dict[str, Any]:
        """Return fresh path-free data; callers cannot mutate this inspection."""
        context = self.context
        return {
            'format': 'opengenjutsu-h3-artifact-set', 'schema_version': 1,
            'assets': {a.role: {'sha256': a.sha256, 'size_bytes': a.size_bytes,
                                'suffix': _SUFFIXES[a.role]} for a in self.assets},
            'context': {'format': 'mctx_v1', 'self_id': context.self_id,
                        'width': context.width, 'height': context.height, 'fps': context.fps,
                        'raw_frames': context.raw_frames, 'delivered_frames': context.delivered_frames},
            'conditioning': {'format': 'obvpm_cond_v1'},
            'verification': {'scope': 'file-integrity-and-media-geometry',
                             'model_runtime_compatibility': False, 'conditioning_tensor_values': False},
        }


def _fingerprint(info) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _resolve(path: str | Path, root: Path, role: str) -> Path:
    if not has_h3_role_suffix(path, role):
        raise ArtifactValidationError('unsupported_suffix', role, 'Artifact has the wrong role suffix')
    try:
        candidate = Path(path)
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=True)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ArtifactValidationError('missing_artifact', role, 'Artifact is missing') from exc
    if not resolved.is_relative_to(root) or resolved == root:
        raise ArtifactValidationError('unsafe_path', role, 'Artifact is outside the allowed media root')
    return resolved


def _inspect(path: Path, role: str):
    """Hash in fixed blocks and inspect through the same regular-file handle."""
    descriptor = None
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None  # fdopen owns it, including exceptional exits.
            initial = os.fstat(stream.fileno())
            if not stat.S_ISREG(initial.st_mode):
                raise ArtifactValidationError('missing_artifact', role, 'Artifact must be a regular file')
            if not initial.st_size:
                raise ArtifactValidationError('empty_artifact', role, 'Artifact is empty')
            header = None
            if role != 'video':
                try:
                    header = read_safetensors_header(stream)
                except HeaderValidationError as exc:
                    raise ArtifactValidationError('invalid_safetensors', role,
                                                  'Invalid or unsupported safetensors envelope') from exc
            if role == 'conditioning':
                if header is None:
                    raise ArtifactValidationError('invalid_safetensors', role, 'Missing conditioning index')
                try:
                    validate_conditioning_structure(stream, header)
                except HeaderValidationError as exc:
                    raise ArtifactValidationError('invalid_conditioning', role,
                                                  'Conditioning structure is invalid or unsupported') from exc
            stream.seek(0)
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            fingerprint = _fingerprint(initial)
            if fingerprint != _fingerprint(os.fstat(stream.fileno())):
                raise ArtifactValidationError('artifact_changed', role, 'Artifact changed during inspection')
        return ArtifactDigest(role, digest.hexdigest(), initial.st_size), header, fingerprint
    except OSError as exc:
        raise ArtifactValidationError('missing_artifact', role, 'Artifact cannot be read as a regular file') from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _format(header: SafetensorsHeader, expected: str, role: str) -> str:
    if header.metadata.get('format') != expected:
        raise ArtifactValidationError('unsupported_format', role, 'Unsupported artifact format version')
    identity = header.metadata.get('self_id', '')
    if not _SHA256.fullmatch(identity):
        raise ArtifactValidationError('invalid_metadata', role, 'Artifact identity must be lowercase SHA-256')
    return identity


def _positive_int(metadata: Mapping[str, str], key: str) -> int:
    text = metadata.get(key, '')
    if not _INTEGER.fullmatch(text) or not 0 < int(text) <= 2**31 - 1:
        raise ArtifactValidationError('invalid_metadata', 'mctx', 'Invalid dimensions or frame counts')
    return int(text)


def _context(header: SafetensorsHeader, identity: str) -> H3Context:
    meta = header.metadata
    width, height = (_positive_int(meta, key) for key in ('width', 'height'))
    raw, delivered = (_positive_int(meta, key) for key in ('raw_frames', 'delivered_frames'))
    try:
        text = meta.get('fps', '')
        if not _FRAME_RATE.fullmatch(text):
            raise ValueError('Unsupported frame-rate literal')
        fps = float(Fraction(text))
        if not math.isfinite(fps) or not 0 < fps <= 1000:
            raise ValueError('Rate is out of range')
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ArtifactValidationError('invalid_metadata', 'mctx', 'Invalid frame rate') from exc
    if delivered > raw or width > 65536 or height > 65536:
        raise ArtifactValidationError('invalid_metadata', 'mctx', 'Inconsistent frame counts or dimensions')
    video, audio = header.tensors.get('video'), header.tensors.get('audio')
    if (video is None or audio is None or video.dtype not in _FLOAT_DTYPES
            or audio.dtype not in _FLOAT_DTYPES or len(video.shape) != 5 or len(audio.shape) != 4
            or video.shape[:2] != (1, 24) or audio.shape[:3] != (1, 32, 2)
            or not all(video.shape) or not all(audio.shape)
            or video.shape[3] * 16 != height or video.shape[4] * 16 != width):
        raise ArtifactValidationError('invalid_latents', 'mctx', 'Unsupported H3 audio/video latent geometry')
    return H3Context(identity, width, height, fps, raw, delivered)


def _check_media(path: Path, context: H3Context) -> None:
    try:
        media = probe_mp4(path)
    except Exception as exc:
        raise ArtifactValidationError('invalid_media', 'video', 'Cannot decode the video metadata') from exc
    if (media.get('width') != context.width or media.get('height') != context.height
            or media.get('frames') != context.delivered_frames
            or not isinstance(media.get('fps'), (int, float))
            or not math.isfinite(media['fps']) or abs(media['fps'] - context.fps) > 1e-6):
        raise ArtifactValidationError('media_mismatch', 'video', 'Video differs from the delivered MCTX geometry')


def _expected(value) -> Mapping[str, str] | None:
    if value is not None and (not isinstance(value, Mapping) or set(value) != set(_SUFFIXES)
                             or any(not isinstance(v, str) or not _SHA256.fullmatch(v)
                                    for v in value.values())):
        raise ArtifactValidationError('invalid_expected_hashes', 'family',
                                      'Expected hashes must cover exactly the three artifact roles')
    return value


def validate_h3_artifact_set(video: str | Path, mctx: str | Path, conditioning: str | Path, *,
                             root: str | Path,
                             expected_sha256: Mapping[str, str] | None = None) -> H3ArtifactSet:
    """Validate an already-local family; never submit, write, or delete anything.

    Paths are explicit, confined beneath a trusted root, and may have different
    stems. Identity is established from bytes, not neighbouring filenames.
    Optional trusted hashes also detect corruption inside latent payloads.
    Stable published files are required; changes during inspection are refused.
    """
    expected = _expected(expected_sha256)
    try:
        root = Path(root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Not a directory')
    except (OSError, ValueError, RuntimeError) as exc:
        raise ArtifactValidationError('unsafe_path', 'family', 'Media root is unavailable') from exc
    paths = {role: _resolve(path, root, role) for role, path in (
        ('video', video), ('mctx', mctx), ('conditioning', conditioning))}
    inspected = {role: _inspect(path, role) for role, path in paths.items()}
    assets = tuple(entry[0] for entry in inspected.values())
    if expected is not None:
        for asset in assets:
            if asset.sha256 != expected[asset.role]:
                raise ArtifactValidationError('digest_mismatch', asset.role, 'Artifact differs from its trusted hash')
    context_header, cond_header = inspected['mctx'][1], inspected['conditioning'][1]
    if context_header is None or cond_header is None:
        raise ArtifactValidationError('invalid_safetensors', 'family', 'Required sidecar index is missing')
    context_id = _format(context_header, 'mctx_v1', 'mctx')
    cond_id = _format(cond_header, 'obvpm_cond_v1', 'conditioning')
    if context_id != inspected['video'][0].sha256 or cond_id != context_id:
        raise ArtifactValidationError('identity_mismatch', 'family', 'MP4, MCTX and COND identities differ')
    context = _context(context_header, context_id)
    _check_media(paths['video'], context)
    # Re-read bytes, not just stat fields: same-size writes can share exactly
    # the same mtime/ctime on real filesystems. Compare parsed headers too: a
    # write between header parsing and hashing must not validate stale metadata.
    # The probe also reopens the MP4.
    for role, path in paths.items():
        try:
            current = _inspect(path, role)
        except ArtifactValidationError as exc:
            raise ArtifactValidationError('artifact_changed', role,
                                          'Artifact changed during inspection') from exc
        if current != inspected[role]:
            raise ArtifactValidationError('artifact_changed', role, 'Artifact changed during inspection')
    return H3ArtifactSet(assets, context)
