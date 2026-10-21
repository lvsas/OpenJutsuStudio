"""Bounded safetensors index inspection, without importing tensor runtimes.

This checks the file envelope and index, not numeric tensor contents. Payloads
remain on disk; callers may explicitly read a small JSON blob by its offsets.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import struct
from types import MappingProxyType
from typing import BinaryIO, Mapping

MAX_HEADER_BYTES = 8 * 1024 * 1024
_MAX_RANK = 16
_DTYPE_BYTES = {
    'BOOL': 1, 'U8': 1, 'I8': 1, 'F8_E4M3': 1, 'F8_E5M2': 1,
    'I16': 2, 'U16': 2, 'F16': 2, 'BF16': 2,
    'I32': 4, 'U32': 4, 'F32': 4,
    'I64': 8, 'U64': 8, 'F64': 8,
}


class HeaderValidationError(ValueError):
    """The envelope cannot be inspected safely with this supported format."""


@dataclass(frozen=True, slots=True)
class TensorIndex:
    dtype: str
    shape: tuple[int, ...]
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SafetensorsHeader:
    metadata: Mapping[str, str]
    tensors: Mapping[str, TensorIndex]
    data_start: int
    file_size: int


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HeaderValidationError('Duplicate JSON object key')
        result[key] = value
    return result


def _reject_constant(_value):
    raise HeaderValidationError('Non-finite JSON number')


def decode_json_bytes(raw: bytes):
    """Decode strict UTF-8 JSON, rejecting duplicate keys and NaN/Infinity."""
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HeaderValidationError('Invalid or excessively nested JSON') from exc


def _tensor_index(value, payload_bytes: int) -> TensorIndex:
    if not isinstance(value, dict) or set(value) != {'dtype', 'shape', 'data_offsets'}:
        raise HeaderValidationError('Malformed tensor index')
    dtype, shape, offsets = value['dtype'], value['shape'], value['data_offsets']
    if not isinstance(dtype, str) or dtype not in _DTYPE_BYTES:
        raise HeaderValidationError('Unsupported tensor dtype')
    if (not isinstance(shape, list) or len(shape) > _MAX_RANK
            or any(type(n) is not int or n < 0 or n > 2**63 - 1 for n in shape)):
        raise HeaderValidationError('Invalid tensor shape')
    if (not isinstance(offsets, list) or len(offsets) != 2
            or any(type(n) is not int for n in offsets)):
        raise HeaderValidationError('Invalid tensor offsets')
    start, end = offsets
    if not 0 <= start <= end <= payload_bytes:
        raise HeaderValidationError('Tensor extends beyond the payload')
    if end - start != math.prod(shape) * _DTYPE_BYTES[dtype]:
        raise HeaderValidationError('Tensor byte length differs from its shape')
    return TensorIndex(dtype, tuple(shape), start, end)


def _check_coverage(tensors: Mapping[str, TensorIndex], payload_bytes: int) -> None:
    cursor = 0
    for tensor in sorted(tensors.values(), key=lambda t: (t.start, t.end)):
        if tensor.start != cursor:
            raise HeaderValidationError('Overlapping tensor data or an unindexed payload gap')
        cursor = tensor.end
    if cursor != payload_bytes:
        raise HeaderValidationError('Trailing unindexed tensor data')


def read_safetensors_header(stream: BinaryIO, *,
                            max_header_bytes: int = MAX_HEADER_BYTES) -> SafetensorsHeader:
    """Inspect a seekable binary file, reading only its bounded JSON header.

    The file must be complete. Offsets cover the payload exactly, including
    legal zero-sized tensors. Metadata additions are retained, but unknown
    tensor dtypes are refused rather than guessed. Leaves the stream at data.
    """
    if type(max_header_bytes) is not int or not 0 < max_header_bytes <= 100 * 1024 * 1024:
        raise ValueError('Header byte limit must be a positive bounded integer')
    stream.seek(0, 2)
    file_size = stream.tell()
    stream.seek(0)
    prefix = stream.read(8)
    if len(prefix) != 8:
        raise HeaderValidationError('Missing safetensors length prefix')
    length = struct.unpack('<Q', prefix)[0]
    if length < 2 or length > max_header_bytes or length > file_size - 8:
        raise HeaderValidationError('Oversized or truncated safetensors header')
    raw = stream.read(length)
    if len(raw) != length or not raw.startswith(b'{'):
        raise HeaderValidationError('Truncated or malformed safetensors header')
    value = decode_json_bytes(raw)
    if not isinstance(value, dict):
        raise HeaderValidationError('Safetensors header must be an object')
    metadata = value.pop('__metadata__', {})
    if (not isinstance(metadata, dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in metadata.items())):
        raise HeaderValidationError('Safetensors metadata must contain only strings')
    if not value:
        raise HeaderValidationError('Safetensors header contains no tensors')
    data_start = 8 + length
    payload_bytes = file_size - data_start
    tensors = {name: _tensor_index(index, payload_bytes) for name, index in value.items()}
    _check_coverage(tensors, payload_bytes)
    return SafetensorsHeader(MappingProxyType(metadata), MappingProxyType(tensors),
                             data_start, file_size)
