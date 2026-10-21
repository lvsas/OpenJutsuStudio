"""Small CPU SDK graphs for native-family re-staging and its literal loader handle.

The native H3 loader exposes a filename COMBO, not a proven STRING socket.
Persist the restager's actual returned clip via the already-used SaveText node,
read its real SDK output, and only then bind that literal in a following job.
This module submits nothing, imports no app configuration, and loads no tensors.
"""
from __future__ import annotations

import io
import re

FAMILY_NODE = 'native_family'
HANDLE_NODE = 'native_clip_handle'
_ROLES = frozenset(('video', 'mctx', 'conditioning'))
_FAMILY = re.compile(r'[a-f0-9]{32}\Z')
_ASSET = re.compile(r'[A-Za-z0-9_.:-]{1,256}\Z')
_HANDLE_LIMIT = 512


def _family(value):
    if not isinstance(value, str) or not _FAMILY.fullmatch(value):
        raise ValueError('A server-generated family identifier is required')
    return value


def _reference(value):
    if not isinstance(value, dict) or value.get('__type') != 'core/ASSET':
        raise ValueError('Every family role requires an actual committed SDK asset reference')
    info = value.get('info')
    identifier = info.get('id') if isinstance(info, dict) else None
    if not isinstance(identifier, str) or not _ASSET.fullmatch(identifier):
        raise ValueError('Invalid SDK asset reference')
    # Keep the authoritative ID, not a requested path/hash hint which may have
    # become stale after deduplication. The proxy resolves each actual asset.
    return {'__type': 'core/ASSET', 'info': {'id': identifier}}


def build_restage_graph(references: dict, family_name: str) -> dict:
    """Build only a confined copy/validate job and an actual handle-text saver.

    ``references`` come from committed SDK assets, never browser filesystem paths.
    This graph alone does not prove an installed pack or native loader execution.
    """
    family_name = _family(family_name)
    if not isinstance(references, dict) or set(references) != _ROLES:
        raise ValueError('Exactly video, mctx and conditioning SDK references are required')
    inputs: dict[str, object] = {role: _reference(references[role]) for role in sorted(_ROLES)}
    inputs['family_name'] = family_name
    return {
        FAMILY_NODE: {'class_type': 'OpenGenjutsuH3RestageFamily', 'inputs': inputs},
        HANDLE_NODE: {'class_type': 'SaveText', 'inputs': {
            'text': [FAMILY_NODE, 0],
            'filename_prefix': f'OpenGenjutsu/continuity/handles/{family_name}/clip',
            'format': 'txt',
        }},
    }


class _BoundedText:
    def __init__(self):
        self.data = io.BytesIO()

    def write(self, block):
        if len(block) > _HANDLE_LIMIT - self.data.tell():
            raise ValueError('SDK clip handle exceeded its byte limit')
        return self.data.write(block)


def read_clip_handle(job, family_name: str) -> str:
    """Read the exact returned loader literal through an actual SDK Output.

    Family media is separately downloaded/validated with h3_artifact_transport.
    This handle is not itself a proof of file integrity or runtime compatibility.
    Never decode/reconstruct an output asset ID to discover a server path.
    """
    from comfy_sdk.outputs import Output

    family_name = _family(family_name)
    if getattr(job, 'status', None) != 'succeeded' or not isinstance(getattr(job, 'id', None), str) or not job.id:
        raise ValueError('A succeeded SDK restaging job is required')
    outputs = list(job.get_outputs(HANDLE_NODE) or [])
    if len(outputs) != 1 or not isinstance(outputs[0], Output):
        raise ValueError('Exactly one actual SDK clip-handle output is required')
    output = outputs[0]
    if (output.node_id != HANDLE_NODE or output.job_id != job.id
            or not isinstance(output.id, str) or not output.id
            or not isinstance(output.name, str) or not output.name.endswith('.txt')
            or any(c in output.name for c in ('/', '\\', '\x00'))
            or output.type not in {'file', 'text'}
            or type(output.size_bytes) is not int or not 0 <= output.size_bytes <= _HANDLE_LIMIT):
        raise ValueError('SDK clip-handle identity or metadata is invalid')
    sink = _BoundedText()
    output.to_stream(sink)
    raw = sink.data.getvalue()
    if not raw or (output.size_bytes and len(raw) != output.size_bytes):
        raise ValueError('SDK clip-handle size differs from its output metadata')
    try:
        handle = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError('SDK clip handle is not UTF-8') from None
    # Accept a text-file line terminator, not whitespace repairs to a path.
    if handle.endswith('\r\n'):
        handle = handle[:-2]
    elif handle.endswith('\n'):
        handle = handle[:-1]
    expected = f'opengenjutsu_continuity/{family_name}/take.mp4'
    if handle != expected:
        raise ValueError('SDK clip handle does not belong to the requested native family')
    return handle
