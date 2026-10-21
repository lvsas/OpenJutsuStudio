"""Validate an OBVPM conditioning tree without constructing torch tensors.

The tagged JSON layout is a persisted data format, not executable code. This
reader checks its references and structure; it cannot certify embedding values
or restore model weights, hooks, or a running ComfyUI process.
"""
from __future__ import annotations

import math
from typing import BinaryIO

from .safetensor_header import HeaderValidationError, SafetensorsHeader, decode_json_bytes

MAX_STRUCTURE_BYTES = 8 * 1024 * 1024
_MAX_TREE_NODES = 100_000
_MAX_TREE_DEPTH = 64
_FLOAT_DTYPES = frozenset({'F16', 'BF16', 'F32', 'F64'})


def _conditioning_entries(tree, header: SafetensorsHeader) -> None:
    if not isinstance(tree, dict) or set(tree) != {'__list__'}:
        raise HeaderValidationError('Conditioning root must be a tagged list')
    entries = tree['__list__']
    if not isinstance(entries, list) or not entries:
        raise HeaderValidationError('Conditioning must contain at least one entry')
    for entry in entries:
        if not isinstance(entry, dict) or len(entry) != 1:
            raise HeaderValidationError('Malformed conditioning entry')
        kind, pair = next(iter(entry.items()))
        if kind not in {'__list__', '__tuple__'} or not isinstance(pair, list) or len(pair) != 2:
            raise HeaderValidationError('Conditioning entry must contain embedding and extras')
        embedding, extras = pair
        if not isinstance(embedding, dict) or set(embedding) != {'__tensor__'}:
            raise HeaderValidationError('Conditioning embedding must reference a tensor')
        key = embedding['__tensor__']
        if not isinstance(key, str) or key not in header.tensors or key == 'structure':
            raise HeaderValidationError('Conditioning embedding tensor is missing')
        tensor = header.tensors[key]
        if tensor.dtype not in _FLOAT_DTYPES or not tensor.shape or not all(tensor.shape):
            raise HeaderValidationError('Conditioning embedding must be a nonempty float tensor')
        if not isinstance(extras, dict) or set(extras) != {'__dict__'}:
            raise HeaderValidationError('Conditioning extras must be a tagged dictionary')


def _check_tree(tree, header: SafetensorsHeader) -> None:
    stack, visited, references = [(tree, 0)], 0, set()
    while stack:
        node, depth = stack.pop()
        visited += 1
        if depth > _MAX_TREE_DEPTH or visited > _MAX_TREE_NODES:
            raise HeaderValidationError('Conditioning structure exceeds inspection limits')
        if node is None or type(node) in {str, int, bool}:
            continue
        if type(node) is float and math.isfinite(node):
            continue
        if not isinstance(node, dict) or len(node) != 1:
            raise HeaderValidationError('Malformed conditioning structure node')
        kind, value = next(iter(node.items()))
        if kind == '__tensor__':
            if not isinstance(value, str) or value == 'structure' or value not in header.tensors:
                raise HeaderValidationError('Conditioning refers to a missing tensor')
            references.add(value)
        elif kind in {'__list__', '__tuple__'} and isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)
        elif kind == '__dict__' and isinstance(value, dict):
            stack.extend((child, depth + 1) for child in value.values())
        else:
            raise HeaderValidationError('Unknown conditioning structure tag')
    if references != set(header.tensors) - {'structure'}:
        raise HeaderValidationError('Conditioning contains unreferenced tensors')


def validate_conditioning_structure(stream: BinaryIO, header: SafetensorsHeader) -> None:
    """Read only the bounded U8 JSON blob and validate all tensor references."""
    blob = header.tensors.get('structure')
    if (blob is None or blob.dtype != 'U8' or len(blob.shape) != 1
            or not 0 < blob.end - blob.start <= MAX_STRUCTURE_BYTES):
        raise HeaderValidationError('Missing or oversized conditioning structure blob')
    stream.seek(header.data_start + blob.start)
    raw = stream.read(blob.end - blob.start)
    if len(raw) != blob.end - blob.start:
        raise HeaderValidationError('Truncated conditioning structure')
    tree = decode_json_bytes(raw)
    _conditioning_entries(tree, header)
    _check_tree(tree, header)
