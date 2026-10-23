#!/usr/bin/env python3
"""Compare project boundary plans to explicit trusted source, offline only.

This checks numerical control flow with shape-only doubles, not tensor values,
GPU execution, the installed target version, codecs, feathering or seam quality.
Reference implementations are loaded from supplied paths, never vendored here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import itertools
import json
from pathlib import Path

import probe_h3_native_boundaries as probe
from h3_av_state import AVState, audio_ticks, quantize_audio_phase
from h3_native_boundaries import NativeBoundaryError, prepare_operation

TARGETS = (90, 124, 141, 158, 175, 192, 243, 277)


def fixture(ref, state):
    return probe.synthetic_state(ref, state.raw_frames, state.pinned_head,
                                 float(state.audio_phase), state.raw_frames - state.raw_end)


def check_plan(ref, plan, parents):
    pins = [probe.prepare_pin(ref, fixture(ref, state), pin.edge, pin.place)
            for state, pin in zip(parents, plan.pins)]
    for expected, actual in zip(plan.pins, pins):
        assert expected.raw_start == actual['spec']['source_start'], 'source video start'
        assert expected.audio_start == actual['spec']['audio_start_step'], 'source audio start'
        assert expected.audio_steps == actual['audio_steps'], 'source audio length'
        assert abs(float(expected.audio_phase) - actual['audio_phase']) < 1e-9, 'source phase'
    head, tail = ref.pins.pins_trim_totals(pins)
    assert (plan.child.pinned_head, plan.pinned_tail) == (head, tail), 'child trims'
    placed = probe.apply_pins(ref, pins, plan.child.raw_frames)
    actual_spans = tuple(tuple(w['target_slice'][-1][:2]) for w in placed['audio_writes'])
    assert actual_spans == plan.target_audio, 'bilateral target audio spans'
    phase = quantize_audio_phase(Fraction(str(placed['child_audio_phase'])))
    assert phase == plan.child.audio_phase, 'saved child phase'
    assert plan.generated_frames == plan.child.raw_frames - sum(p['covered'] for p in pins), 'generated space'
    if plan.source_exit is not None:
        start = pins[0]['spec']['source_start'] - parents[0].pinned_head
        cut = ref.masked.handover_frames(39, 'before', decode_edge=True)
        assert plan.source_exit == start + cut, 'left source handover'
    if plan.destination_entry is not None:
        cut = ref.masked.handover_frames(39, 'after', decode_edge=True)
        assert plan.destination_entry == cut, 'right destination handover'
    # Reconstruct six-decimal child metadata and execute the reference slicer and
    # masked placement again. This is a header projection, not a saver/VAE run.
    future = probe.prepare_pin(ref, fixture(ref, plan.child), 'tail', 'before')
    probe.apply_pin(ref, future, 192)


def run_comparison(ref, work=None):
    states = [AVState(raw, head, raw - head, audio_ticks(raw), Fraction(str(phase)))
              for raw, head, phase in itertools.product((56, 124, 158, 192), (0, 35),
                                                       probe.PHASE_CASES)]
    cases = [(mode, (state,), raw) for mode, state, raw in
             itertools.product(('forward', 'prepend'), states, TARGETS)]
    heads = [state for state in states if state.pinned_head == 0]
    cases += [('bridge', (left, right), raw)
              for left, right, raw in itertools.product(states, heads, TARGETS)]
    measured = 0
    scan = None
    if work is not None:
        headers, scan = probe.measured_states(work)
        real = [AVState(**{**h['project_av_state'],
                          'audio_phase': Fraction(h['project_av_state']['audio_phase'])}) for h in headers]
        measured = len(real)
        cases += [(mode, (state,), raw) for mode, state, raw in
                  itertools.product(('forward', 'prepend'), real, TARGETS)]
        cases += [('bridge', (left, right), raw)
                  for i, left in enumerate(real) for j, right in enumerate(real) if i != j
                  for raw in TARGETS]
    accepted, rejected, mismatches = Counter(), Counter(), []
    for mode, parents, raw in cases:
        try:
            plan = prepare_operation(mode, parents, raw)
        except NativeBoundaryError as exc:
            rejected[mode + ':' + exc.code] += 1
            continue
        try:
            check_plan(ref, plan, parents)
        except (AssertionError, ValueError, RuntimeError) as exc:
            mismatches.append({'mode': mode, 'raw_frames': raw,
                               'parents': [{'raw_frames': p.raw_frames, 'pinned_head': p.pinned_head,
                                            'delivered_frames': p.delivered_frames,
                                            'audio_phase': str(p.audio_phase)} for p in parents],
                               'error': type(exc).__name__ + ': ' + str(exc)})
        else:
            accepted[mode] += 1
    if any(not accepted[mode] for mode in ('forward', 'prepend', 'bridge')):
        mismatches.append({'error': 'At least one mode had no accepted reference comparison'})
    assert len(cases) == sum(accepted.values()) + sum(rejected.values()) + sum('mode' in m for m in mismatches)
    return {'schema': 'h3-native-boundary-policy-comparison-v1',
            'evidence_kind': 'numeric_control_flow_with_shape_only_doubles',
            'cases': len(cases), 'matched': dict(accepted), 'policy_refusals': dict(rejected),
            'mismatches': mismatches, 'measured_headers': measured, 'work_scan': scan,
            'sources': ref.sources,
            'limits': ['No GPU, tensor values, decoded media, installed-source identity or seam-quality proof.',
                       'Exact named reference functions execute with shape-only doubles and audio feather=0.',
                       'Accepted policies are compared; conservative product refusals need not be upstream errors.',
                       'Bridge fixtures compare temporal state, not parent identity, geometry or weight attestations.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for role in ('pins', 'masked', 'frames'):
        parser.add_argument('--' + role + '-source', type=Path, required=True)
    parser.add_argument('--work', type=Path)
    args = parser.parse_args()
    ref = probe.load_reference(args.pins_source, args.masked_source, args.frames_source)
    report = run_comparison(ref, args.work)
    print(json.dumps(report, indent=2, allow_nan=False))
    return int(bool(report['mismatches']))


if __name__ == '__main__':
    raise SystemExit(main())
