"""Pure native-boundary policy, not an enabled Prepend/Bridge execution adapter.

Scope: exact 39-frame hard masked windows under the examined OBVPM policy.
Keep this numerical contract separate from runtime capability and perceptual proof.
No source mutation, snapping, pixel conversion or target interaction occurs here.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from h3_av_state import (AVState, FORWARD_HEAD, FRAME_RESCALE, GRID_OFFSET, GRID_STEP,
                         PHASE_SCALE, WINDOW, audio_ticks, quantize_audio_phase,
                         window_at)

# Hard-masked decode-edge handovers in the reference policy: keep four departing
# frames and five arriving frames in the child, rather than reusing decode edges.
AFTER_ENTRY = 5
AFTER_TAIL = WINDOW - AFTER_ENTRY
PHASE_TOLERANCE = Fraction(2, PHASE_SCALE)
_MESSAGES = {
    'contract': 'The native operation or its anchors are incomplete. Nothing was submitted.',
    'state': 'The saved timing is inconsistent. Choose another take; the original is unchanged.',
    'short_source': 'This take is too short for the requested handover. Choose another take.',
    'unaligned_start': 'This take\'s exact start cannot be used by this native operation. '
                       'Choose another anchor; no cut was moved.',
    'unaligned_end': 'This take\'s exact end cannot be used by this native operation. '
                     'Choose another anchor; no cut was moved.',
    'audio_window': 'The saved sound cannot supply the complete handover. Choose another anchor.',
    'length': 'This duration is not compatible with the native operation. Nothing was submitted.',
    'after_audio_grid': 'This duration cannot preserve the arrival sound. Choose a compatible duration.',
    'audio_phase_conflict': 'These anchors have incompatible sound timing. No bridge was submitted.',
    'no_generated_space': 'This duration leaves no room for new footage. Choose a longer duration.',
    'child_tail': 'The result would be too short or incompatible for a further continuation. '
                  'Choose another duration; nothing was submitted.',
}


class NativeBoundaryError(ValueError):
    """Bounded refusal with static operator-facing copy, not private state dumps."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(_MESSAGES[code])


@dataclass(frozen=True, slots=True)
class SourcePin:
    edge: str
    place: str
    raw_start: int
    audio_start: int
    audio_steps: int
    audio_phase: Fraction


@dataclass(frozen=True, slots=True)
class NativeOperationPlan:
    mode: str
    pins: tuple[SourcePin, ...]
    target_audio: tuple[tuple[int, int], ...]
    child: AVState
    generated_frames: int
    source_exit: int | None
    destination_entry: int | None

    @property
    def pinned_tail(self) -> int:
        return self.child.raw_frames - self.child.raw_end


def _check_state(state: AVState) -> None:
    if not isinstance(state, AVState):
        raise NativeBoundaryError('state')
    counts = (state.raw_frames, state.pinned_head, state.delivered_frames, state.audio_ticks)
    if (any(type(n) is not int for n in counts) or not 5 <= state.raw_frames <= 3600
            or (state.raw_frames - GRID_OFFSET) % GRID_STEP
            or state.pinned_head < 0 or state.delivered_frames < 0
            or state.raw_end > state.raw_frames or state.audio_ticks <= 0
            or not isinstance(state.audio_phase, Fraction) or not -8 < state.audio_phase < 8):
        raise NativeBoundaryError('state')


def source_pin(state: AVState, edge: str, place: str) -> SourcePin:
    """Check the exact delivered boundary; do not move it onto another cut."""
    _check_state(state)
    if (edge, place) not in (('head', 'after'), ('tail', 'before')):
        raise NativeBoundaryError('contract')
    if state.delivered_frames < WINDOW:
        raise NativeBoundaryError('short_source')
    start = state.pinned_head if edge == 'head' else state.raw_end - WINDOW
    if start % GRID_STEP:
        raise NativeBoundaryError('unaligned_start' if edge == 'head' else 'unaligned_end')
    if start < 0 or start + WINDOW > state.raw_frames:
        raise NativeBoundaryError('state')
    _, first, wanted, available = window_at(state, start)
    if available != wanted:
        raise NativeBoundaryError('audio_window')
    phase = state.audio_phase + first - start * FRAME_RESCALE
    return SourcePin(edge, place, start, first, wanted, phase)


def prepare_operation(mode: str, parents: tuple[AVState, ...], raw_frames: int) -> NativeOperationPlan:
    """Project explicit boundaries and a reusable child before any execution.

    Geometry, weights, exact parent identities, target capability and collection
    are the caller's separate contracts. A plan is not an executed native take.
    """
    if (mode not in ('forward', 'prepend', 'bridge') or not isinstance(parents, (tuple, list))
            or len(parents) != (2 if mode == 'bridge' else 1)):
        raise NativeBoundaryError('contract')
    if (type(raw_frames) is not int or not 5 <= raw_frames <= 3600
            or (raw_frames - GRID_OFFSET) % GRID_STEP):
        raise NativeBoundaryError('length')
    has_before, has_after = mode != 'prepend', mode != 'forward'
    if has_after and raw_frames % 3:
        raise NativeBoundaryError('after_audio_grid')
    pins = []
    if has_before:
        pins.append(source_pin(parents[0], 'tail', 'before'))
    if has_after:
        pins.append(source_pin(parents[-1], 'head', 'after'))
    generated = raw_frames - WINDOW * len(pins)
    if generated <= 0:
        raise NativeBoundaryError('no_generated_space')
    ticks = audio_ticks(raw_frames)
    span = int(WINDOW * FRAME_RESCALE)
    target = tuple((0, span) if p.place == 'before' else (ticks - span, ticks) for p in pins)
    # A before-pin fixes the global grid. An after-pin must describe the same
    # grid; allow only rounding already introduced by six-decimal saved metadata.
    phases = tuple(p.audio_phase - (lo - (0 if p.place == 'before' else raw_frames - WINDOW)
                                   * FRAME_RESCALE) for p, (lo, _) in zip(pins, target))
    if max(phases) - min(phases) > PHASE_TOLERANCE:
        raise NativeBoundaryError('audio_phase_conflict')
    head = FORWARD_HEAD if has_before else 0
    tail = AFTER_TAIL if has_after else 0
    child = AVState(raw_frames, head, raw_frames - head - tail, ticks,
                    quantize_audio_phase(phases[0]))
    try:
        source_pin(child, 'tail', 'before')
    except NativeBoundaryError as exc:
        raise NativeBoundaryError('child_tail') from exc
    return NativeOperationPlan(mode, tuple(pins), target, child, generated,
                               parents[0].delivered_frames - (WINDOW - FORWARD_HEAD)
                               if has_before else None,
                               AFTER_ENTRY if has_after else None)
