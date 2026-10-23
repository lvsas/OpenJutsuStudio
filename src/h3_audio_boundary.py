"""Read-only refusal of known incompatible phase-aware masked tail windows.

This is not a tensor repair or a general runtime compatibility certificate.
Unknown legacy phase policies remain outside this bounded check.
"""
from fractions import Fraction
import math
from pathlib import Path

from safetensor_header import read_safetensors_header

MESSAGE = ('This take has an incompatible saved audio boundary and cannot currently '
           'be extended. No GPU work was started; the original take is unchanged.')


class IncompatibleAudioBoundary(ValueError):
    def __init__(self):
        super().__init__(MESSAGE)


def require_complete_masked_tail(header, window=39):
    """Mirror the phase-aware nearest-tick rule without changing saved bytes."""
    meta = header.metadata
    if 'audio_phase' not in meta:
        return  # No claim about older recipes whose phase must be reconstructed.
    try:
        value = meta['audio_phase']
        if not isinstance(value, str) or len(value) > 64:
            raise IncompatibleAudioBoundary()
        numeric = float(value)
        if not math.isfinite(numeric):
            raise IncompatibleAudioBoundary()
        # Float normalization matches the runtime and bounds exponent parsing.
        phase = Fraction(str(numeric))
        delivered = int(meta['delivered_frames'])
        head = int(meta.get('pinned_head_frames', '0'))
        raw = int(meta['raw_frames'])
        ticks = header.tensors['audio'].shape[-1]
        end = head + delivered
        start = end - window
        if start < 0 or end > raw:
            raise IncompatibleAudioBoundary()
        # slice_step = floor(frame * 5/3 - source_phase + 1/2).
        coordinate = Fraction(start * 5, 3) - phase + Fraction(1, 2)
        first_tick = max(0, coordinate.numerator // coordinate.denominator)
        wanted = Fraction(window * 5, 3)
        if wanted.denominator != 1:
            raise IncompatibleAudioBoundary()
        available = max(0, min(ticks, first_tick + int(wanted)) - first_tick)
        if available != wanted:
            raise IncompatibleAudioBoundary()
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise IncompatibleAudioBoundary() from exc


def require_family_masked_tail(family):
    # Lightweight context-only attestations are also used by native_parent;
    # production submission/readiness obtains paths from get_validated_family.
    path = getattr(family, 'mctx', None)
    if isinstance(path, Path):
        with path.open('rb') as stream:
            require_complete_masked_tail(read_safetensors_header(stream))
