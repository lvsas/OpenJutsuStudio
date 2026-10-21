"""Fail-closed download of an already-published, single-node SDK H3 family.

This is not a saver, uploader, loader, graph runner, or legacy HTTP fallback.
An opaque STRING path cannot be upgraded to an SDK output here. The caller
must already have a succeeded SDK job with all three published outputs.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from comfy_sdk.outputs import Output
from comfy_transport import _publish_directory
from timeline_artifacts import H3ArtifactSet, validate_h3_artifact_set

_SUFFIXES = {'video': '.mp4', 'mctx': '.mctx.safetensors',
             'conditioning': '.cond.safetensors'}
_DEFAULT_MAX = {role: 512 * 1024 * 1024 for role in _SUFFIXES}
_NODE = re.compile(r'(?:\d+|\d+:\d+|[A-Za-z_][A-Za-z0-9_]*)\Z')


class _LimitedWriter:
    """Cap actual bytes, including SDK outputs advertising unknown (zero) size."""

    def __init__(self, stream, limit: int):
        self.stream, self.limit, self.written = stream, limit, 0

    def write(self, block: bytes) -> int:
        if len(block) > self.limit - self.written:
            raise ValueError('SDK artifact exceeds its role byte limit')
        count = self.stream.write(block)
        self.written += count
        return count


def download_h3_artifacts(job, node_id: str, folder: str | Path, *,
                          expected_sha256: Mapping[str, str] | None = None,
                          max_bytes: Mapping[str, int] | None = None) -> H3ArtifactSet:
    """Validate and atomically publish exactly three actual SDK outputs.

    All roles must belong to ``job.id`` and ``node_id``. Roles are selected
    only from published output suffixes, never guessed adjacent server paths.
    Byte identities/geometry are checked by ``validate_h3_artifact_set`` before
    exposing the destination. Remote names are not used as local paths. The
    destination parent is a caller-owned trusted directory. No network request
    other than each selected Output's public ``to_stream`` is issued here.

    This intentionally supports only a single publishing node, not an inferred
    multi-node association. Source/loader compatibility remains unproven.
    """
    if not isinstance(node_id, str) or not _NODE.fullmatch(node_id):
        raise ValueError('Invalid SDK output node identifier')
    if job.status != 'succeeded' or not isinstance(job.id, str) or not job.id:
        raise ValueError('A succeeded SDK job with an identifier is required')
    limits = dict(_DEFAULT_MAX if max_bytes is None else max_bytes)
    if set(limits) != set(_SUFFIXES) or any(
            type(value) is not int or not 0 < value <= 2 * 1024**3 for value in limits.values()):
        raise ValueError('Byte limits must cover exactly the three supported roles')
    destination = Path(folder)
    if os.path.lexists(destination):
        raise FileExistsError('SDK H3 destination already exists')
    outputs = list(job.get_outputs(node_id) or [])
    selected = {}
    for output in outputs:
        if not isinstance(output, Output):
            raise ValueError('A STRING path or descriptor is not a published SDK Output')
        if (output.job_id != job.id or output.node_id != node_id
                or not isinstance(output.id, str) or not output.id):
            raise ValueError('SDK output job/node association is missing or inconsistent')
        name = output.name
        if (not isinstance(name, str) or not name or len(name) > 255
                or any(c in name for c in ('/', '\\', '\x00'))):
            raise ValueError('Unsafe SDK artifact filename')
        roles = [role for role, suffix in _SUFFIXES.items() if name.endswith(suffix)]
        if len(roles) != 1 or roles[0] in selected:
            raise ValueError('Missing, duplicate or unsupported SDK artifact role')
        role = roles[0]
        allowed_types = {'video', 'file'} if role == 'video' else {'file', 'latent'}
        if (output.type not in allowed_types or type(output.size_bytes) is not int
                or output.size_bytes < 0 or output.size_bytes > limits[role]):
            raise ValueError('SDK artifact type or size is outside its role limits')
        if any(previous.id == output.id for previous in selected.values()):
            raise ValueError('One SDK asset cannot fill multiple artifact roles')
        selected[role] = output
    if set(selected) != set(_SUFFIXES):
        raise ValueError('SDK node has not published the complete MP4/MCTX/COND family')

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f'.{destination.name}.', suffix='.part',
                                    dir=destination.parent))
    try:
        paths = {}
        for role, output in selected.items():
            path = staging / ('take' + _SUFFIXES[role])
            with path.open('xb') as stream:
                sink = _LimitedWriter(stream, limits[role])
                output.to_stream(sink)
            if not sink.written or (output.size_bytes and sink.written != output.size_bytes):
                raise ValueError('Downloaded SDK artifact size differs from its descriptor')
            paths[role] = path
        inspected = validate_h3_artifact_set(**paths, root=staging,
                                              expected_sha256=expected_sha256)
        (staging / 'manifest.json').write_text(
            json.dumps(inspected.to_manifest(), indent=2, sort_keys=True) + '\n')
        _publish_directory(staging, destination)
        return inspected
    finally:
        if staging.exists():
            shutil.rmtree(staging)
