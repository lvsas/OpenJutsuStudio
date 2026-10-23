"""Pure contract fixtures: no render, target mutation or model dependency."""
from fractions import Fraction
from types import SimpleNamespace
import unittest

from h3_av_state import AVState, audio_ticks, child_state, state_from_header
from h3_native_boundaries import NativeBoundaryError, prepare_operation, source_pin


def root(raw=192, phase=Fraction(0)):
    return AVState(raw, 0, raw, audio_ticks(raw), phase)


class NativeBoundaryTests(unittest.TestCase):
    def test_exact_forward_child_head_is_refused_without_moving_it(self):
        parent = AVState(158, 35, 123, 263, Fraction(0))
        with self.assertRaises(NativeBoundaryError) as error:
            source_pin(parent, 'head', 'after')
        self.assertEqual(error.exception.code, 'unaligned_start')
        self.assertNotIn('frames', str(error.exception))
        self.assertEqual(parent.pinned_head, 35)
        self.assertEqual(source_pin(parent, 'tail', 'before').raw_start, 119)

    def test_a_complete_window_and_delivered_capacity_are_both_required(self):
        short = AVState(56, 35, 21, 93, Fraction(0))
        with self.assertRaises(NativeBoundaryError):
            source_pin(short, 'tail', 'before')
        dead = AVState(158, 35, 123, 263, Fraction(-333333, 1000000))
        with self.assertRaises(NativeBoundaryError) as error:
            source_pin(dead, 'tail', 'before')
        self.assertEqual(error.exception.code, 'audio_window')

    def test_forward_projection_matches_existing_saved_state_arithmetic(self):
        parent = AVState(124, 35, 89, 207, Fraction(-333333, 1000000))
        plan = prepare_operation('forward', (parent,), 158)
        self.assertEqual(plan.child, child_state(parent, 158))
        self.assertEqual(plan.target_audio, ((0, 65),))
        self.assertEqual(plan.source_exit, 85)
        self.assertIsNone(plan.destination_entry)

    def test_prepend_is_new_footage_leading_into_the_head_not_reverse(self):
        parent = root()
        plan = prepare_operation('prepend', (parent,), 192)
        self.assertEqual((plan.pins[0].edge, plan.pins[0].place), ('head', 'after'))
        self.assertEqual((plan.child.pinned_head, plan.pinned_tail), (0, 34))
        self.assertEqual(plan.child.delivered_frames, 158)
        self.assertEqual(plan.generated_frames, 153)
        self.assertEqual(plan.target_audio, ((255, 320),))
        self.assertIsNone(plan.source_exit)
        self.assertEqual(plan.destination_entry, 5)
        self.assertEqual(parent, root())

    def test_bridge_carries_ordered_ends_and_explicit_handover_ranges(self):
        left, right = root(192), root(56)
        plan = prepare_operation('bridge', (left, right), 192)
        self.assertEqual([(p.edge, p.place) for p in plan.pins],
                         [('tail', 'before'), ('head', 'after')])
        self.assertEqual(plan.target_audio, ((0, 65), (255, 320)))
        self.assertEqual((plan.child.pinned_head, plan.pinned_tail), (35, 34))
        self.assertEqual(plan.child.delivered_frames, 123)
        self.assertEqual(plan.generated_frames, 114)
        self.assertEqual((plan.source_exit, plan.destination_entry), (188, 5))
        self.assertEqual(plan.child.audio_phase, 0)
        with self.assertRaises(NativeBoundaryError):
            source_pin(plan.child, 'head', 'after')
        source_pin(plan.child, 'tail', 'before')

    def test_bridge_refuses_disagreeing_endpoint_audio_phase(self):
        # Both source windows fit individually, but one global child phase cannot
        # preserve their different audio/video offsets on a shared-grid run.
        source_pin(root(56), 'tail', 'before')
        source_pin(root(192), 'head', 'after')
        with self.assertRaises(NativeBoundaryError) as error:
            prepare_operation('bridge', (root(56), root(192)), 192)
        self.assertEqual(error.exception.code, 'audio_phase_conflict')

    def test_prepend_phases_survive_six_decimal_header_roundtrip_and_repetition(self):
        for phase in (Fraction(0), Fraction(-333333, 1000000), Fraction(333333, 1000000)):
            parent = root(192, phase)
            for _ in range(6):
                plan = prepare_operation('prepend', (parent,), 192)
                saved = SimpleNamespace(metadata={
                    'raw_frames': str(plan.child.raw_frames),
                    'pinned_head_frames': str(plan.child.pinned_head),
                    'pinned_tail_frames': str(plan.pinned_tail),
                    'delivered_frames': str(plan.child.delivered_frames),
                    'audio_phase': f'{float(plan.child.audio_phase):.6f}'},
                    tensors={'audio': SimpleNamespace(shape=(1, 32, 2, plan.child.audio_ticks))})
                parent = state_from_header(saved)
                self.assertEqual(parent, plan.child)
                source_pin(parent, 'head', 'after')
                source_pin(parent, 'tail', 'before')

    def test_after_pin_lengths_do_not_silently_snap_to_another_duration(self):
        for mode, parents in (('prepend', (root(),)), ('bridge', (root(), root(56)))):
            with self.subTest(mode=mode), self.assertRaises(NativeBoundaryError) as error:
                prepare_operation(mode, parents, 158)
            self.assertEqual(error.exception.code, 'after_audio_grid')

    def test_no_generated_interval_or_future_tail_is_not_an_accepted_take(self):
        for mode, parents, raw in (('prepend', (root(),), 39),
                                   ('bridge', (root(), root(56)), 39),
                                   ('bridge', (root(), root(56)), 90)):
            with self.subTest(mode=mode, raw=raw), self.assertRaises(NativeBoundaryError):
                prepare_operation(mode, parents, raw)

    def test_contract_shape_and_native_lengths_fail_closed(self):
        cases = [('unknown', (root(),), 192), ('bridge', (root(),), 192),
                 ('forward', (root(), root(56)), 192), ('prepend', (), 192),
                 ('prepend', (None,), 192), ('prepend', (root(),), True),
                 ('prepend', (root(),), 193), ('prepend', (root(),), 3609)]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(NativeBoundaryError):
                prepare_operation(*args)

    def test_bounded_grid_matrix_preserves_child_tail_and_source_inputs(self):
        accepted = set()
        for phase in (Fraction(0), Fraction(-333333, 1000000), Fraction(333333, 1000000)):
            left = root(192, phase)
            for mode, parents in (('forward', (left,)), ('prepend', (left,)),
                                  ('bridge', (left, root(192, phase)))):
                for raw in range(5, 601, 17):
                    try:
                        plan = prepare_operation(mode, parents, raw)
                    except NativeBoundaryError:
                        continue
                    accepted.add(mode)
                    with self.subTest(mode=mode, phase=phase, raw=raw):
                        self.assertGreater(plan.generated_frames, 0)
                        source_pin(plan.child, 'tail', 'before')
                        self.assertEqual(plan.child.raw_end + plan.pinned_tail, raw)
                        for lo, hi in plan.target_audio:
                            self.assertEqual(hi - lo, 65)
                            self.assertGreaterEqual(lo, 0)
                            self.assertLessEqual(hi, plan.child.audio_ticks)
                        self.assertEqual(left, root(192, phase))
        self.assertEqual(accepted, {'forward', 'prepend', 'bridge'})

    def test_parent_timing_bounds_are_checked_before_any_window_projection(self):
        for state in (AVState(192, -1, 193, 320, Fraction(0)),
                      AVState(192, 35, 192, 320, Fraction(0)),
                      AVState(192, 0, 192, 320, Fraction(9))):
            with self.subTest(state=state), self.assertRaises(NativeBoundaryError):
                source_pin(state, 'tail', 'before')
