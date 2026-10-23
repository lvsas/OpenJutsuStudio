"""The audio/video state arithmetic a continuation must satisfy.

Why this module exists: a take that cannot be continued by the same adapter that
produced it is a dead end sold as a future. The installed masked-pin policy
(`comfyui-obvpm-timeline` 03a4b83f) slices a 39-frame tail from the audio step
nearest the window's first frame, and refuses when the stored audio grid cannot
supply a whole window. Whether that happens is a property of the *saved* state
(ticks, pinned head, delivered frames, audio phase), not of the graph that asked
for it — measured on a real job: 158 frames, 263 ticks, phase -1/3 selects tick
199 and needs 264, so the mask sees 64 of 65 steps.

So the application computes the state it is about to create, and refuses a length
whose take would itself be uncontinuable — before any upload, refiner or sampling.
That is an invariant of our product, not a patch of the third-party node: unmodified
runtime, unmodified ComfyUI core, same check on a workstation or a remote target.
Where a target's node policy differs, its own refusal stays authoritative.

Scope: forward continuations (one 39-frame masked tail at the parent's end). Other
operations carry their own state rules and must not reuse this silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import floor
from pathlib import Path

from safetensor_header import read_safetensors_header

WINDOW = 39
GRID_OFFSET = 5
GRID_STEP = 17
FPS = 24
AUDIO_LATENT_FPS = 40
FRAME_RESCALE = Fraction(AUDIO_LATENT_FPS, FPS)      # 5/3 audio steps per frame
FORWARD_HEAD = 35                                     # frames the pin removes
PHASE_SCALE = 1_000_000                               # the saver stores six decimals

UNCONTINUABLE_TAKE = (
    'This take cannot be continued: its saved footage or audio timing cannot supply '
    'the handover the next take needs. It is unchanged; start from another take.')
UNCONTINUABLE_LENGTH = (
    'An extension of about {requested} s could not be continued afterwards. '
    'It was not submitted. Compatible new footage here: {options}.')


class AVStateError(ValueError):
    """Saved state that cannot carry a masked tail."""


class UncontinuableLength(ValueError):
    """The requested length would produce a take that is itself a dead end."""


@dataclass(frozen=True, slots=True)
class AVState:
    """The measured facts a saved take contributes to the next generation."""
    raw_frames: int
    pinned_head: int
    delivered_frames: int
    audio_ticks: int
    audio_phase: Fraction

    @property
    def raw_end(self) -> int:
        return self.pinned_head + self.delivered_frames


def audio_ticks(raw_frames: int) -> int:
    """ComfyUI's own allocation: round(duration * 40) at 24 fps."""
    return round(Fraction(raw_frames, FPS) * AUDIO_LATENT_FPS)


def tail_window(state: AVState, window: int = WINDOW) -> tuple[int, int, int, int]:
    """(start frame, first tick, ticks wanted, ticks available) at the take's end."""
    start = state.raw_end - window
    if start < 0:
        return -1, 0, 0, 0
    coordinate = Fraction(start) * FRAME_RESCALE - state.audio_phase + Fraction(1, 2)
    first = max(0, floor(coordinate))
    wanted = int(Fraction(window) * FRAME_RESCALE)
    available = max(0, min(state.audio_ticks, first + wanted) - first)
    return start, first, wanted, available


def tail_fits(state: AVState, window: int = WINDOW) -> bool:
    if state.delivered_frames < window:
        return False
    start, _, wanted, available = tail_window(state, window)
    return start >= 0 and wanted == window * 5 // 3 and available == wanted


def _quantize(phase: Fraction) -> Fraction:
    return Fraction(round(float(phase) * PHASE_SCALE), PHASE_SCALE)


def child_state(parent: AVState, requested_raw: int, window: int = WINDOW) -> AVState:
    """The state a forward would freeze, computed from the documented policy.

    Raises ``AVStateError`` when the parent cannot supply the window, so a caller
    cannot accidentally project a generation that is already known to fail.
    """
    if not tail_fits(parent, window):
        raise AVStateError(UNCONTINUABLE_TAKE)
    start, first, _, _ = tail_window(parent, window)
    phase = _quantize(parent.audio_phase + Fraction(first) - Fraction(start) * FRAME_RESCALE)
    return AVState(raw_frames=requested_raw, pinned_head=FORWARD_HEAD,
                   delivered_frames=requested_raw - FORWARD_HEAD,
                   audio_ticks=audio_ticks(requested_raw), audio_phase=phase)


def requested_lengths(parent: AVState, window: int = WINDOW, limit: int = 3600) -> list[int]:
    """Native lengths that would leave *this* parent's child continuable."""
    safe = []
    for raw in range(GRID_OFFSET, limit + 1, GRID_STEP):
        try:
            if tail_fits(child_state(parent, raw, window), window):
                safe.append(raw)
        except AVStateError:
            return []
    return safe


def require_continuable_child(parent: AVState, requested_raw: int,
                              window: int = WINDOW) -> AVState:
    """Refuse a length whose produced take could not be continued afterwards."""
    child = child_state(parent, requested_raw, window)
    if tail_fits(child, window):
        return child
    options = requested_lengths(parent, window)
    nearest = sorted(options, key=lambda raw: (abs(raw - requested_raw), raw))[:3]
    raise UncontinuableLength(UNCONTINUABLE_LENGTH.format(
        requested=f'{max(0, requested_raw - FORWARD_HEAD) / FPS:.1f}',
        options=', '.join(f'{(raw - FORWARD_HEAD) / FPS:.1f} s' for raw in nearest)
        or 'none for this take'))


def state_from_header(header) -> AVState:
    """Read the saved A/V state from a validated mctx header.

    Only explicit phase metadata is used: an older recipe's phase must be
    reconstructed by its own policy, so this model does not guess it.
    """
    meta = header.metadata
    if 'audio_phase' not in meta:
        raise AVStateError('This take does not record its audio phase')
    value = meta['audio_phase']
    if not isinstance(value, str) or len(value) > 64:
        raise AVStateError(UNCONTINUABLE_TAKE)
    numeric = float(value)
    if not (-8.0 < numeric < 8.0):
        raise AVStateError(UNCONTINUABLE_TAKE)
    return AVState(raw_frames=int(meta['raw_frames']),
                   pinned_head=int(meta.get('pinned_head_frames', '0') or 0),
                   delivered_frames=int(meta['delivered_frames']),
                   audio_ticks=int(header.tensors['audio'].shape[-1]),
                   audio_phase=_quantize(Fraction(str(numeric))))


def state_from_family(family):
    """A validated family's state, or None for an inspection double with no file."""
    path = getattr(family, 'mctx', None)
    if not isinstance(path, Path):
        return None
    with path.open('rb') as stream:
        return state_from_header(read_safetensors_header(stream))
