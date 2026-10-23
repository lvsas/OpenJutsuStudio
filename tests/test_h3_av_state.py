"""A take we create must itself be continuable; refusal happens before any cost."""
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import continuity_pipeline as pipeline
from h3_av_state import (AVState, AVStateError, UncontinuableLength, audio_ticks,
                         child_state, requested_lengths, require_continuable_child,
                         tail_fits, tail_window)
from test_continuity_pipeline import MODELS, TAKE


def context_family(raw, delivered):
    manifest = {'context': {'format': 'mctx_v1', 'width': 1280, 'height': 704, 'fps': 24,
                            'raw_frames': raw, 'delivered_frames': delivered}}
    return SimpleNamespace(to_manifest=lambda: manifest)

# Measured on real takes in the project store (mctx metadata + tensor shape).
PARENT_DEAD = AVState(158, 35, 123, 263, Fraction(-333333, 1_000_000))   # 399c63e1
PARENT_OK = AVState(124, 35, 89, 207, Fraction(-333333, 1_000_000))      # 6423dea7
PARENT_192 = AVState(192, 35, 157, 320, Fraction(333333, 1_000_000))     # f78dc426
PARENT_ROOT = AVState(56, 0, 56, 93, Fraction(0))                        # ffc7e3d3


class AudioGridTests(unittest.TestCase):
    def test_allocation_is_comfyui_round_not_ceiling(self):
        self.assertEqual([audio_ticks(n) for n in (56, 124, 158, 192)],
                         [93, 207, 263, 320])


class TailWindowTests(unittest.TestCase):
    def test_the_reported_failure_is_reproduced_exactly(self):
        self.assertEqual(tail_window(PARENT_DEAD), (119, 199, 65, 64))
        self.assertFalse(tail_fits(PARENT_DEAD))

    def test_takes_that_continue_correctly(self):
        for state in (PARENT_OK, PARENT_192, PARENT_ROOT):
            self.assertTrue(tail_fits(state), state)
        self.assertEqual(tail_window(PARENT_OK), (85, 142, 65, 65))

    def test_a_short_take_cannot_supply_the_window(self):
        too_short = AVState(56, 35, 21, 93, Fraction(-333333, 1_000_000))
        self.assertFalse(tail_fits(too_short))


class ChildProjectionTests(unittest.TestCase):
    def test_projection_records_the_phase_the_saver_will_store(self):
        child = child_state(PARENT_OK, 158)
        self.assertEqual((child.pinned_head, child.delivered_frames, child.audio_ticks),
                         (35, 123, 263))
        self.assertEqual(child.audio_phase, 0)          # no drift from this parent
        self.assertTrue(tail_fits(child))

    def test_a_length_that_would_dead_end_the_next_take_is_refused(self):
        root = AVState(362, 0, 362, audio_ticks(362), Fraction(0))
        self.assertTrue(tail_fits(root))                # this parent is fine today
        with self.assertRaises(UncontinuableLength) as caught:
            require_continuable_child(root, 362)
        message = str(caught.exception)
        self.assertIn('not submitted', message)
        self.assertIn('frames', message)

    def test_refusal_names_reachable_lengths_for_that_parent(self):
        root = AVState(362, 0, 362, audio_ticks(362), Fraction(0))
        safe = requested_lengths(root)
        self.assertTrue(safe)
        self.assertNotIn(362, safe)
        for raw in safe[:5]:
            self.assertTrue(tail_fits(child_state(root, raw)))

    def test_an_unusable_parent_is_reported_as_such(self):
        with self.assertRaises(AVStateError):
            child_state(PARENT_DEAD, 158)

    def test_the_invariant_survives_repeated_generations(self):
        """Every child we accept is itself accepted as a parent."""
        state = AVState(192, 0, 192, audio_ticks(192), Fraction(0))
        for generation in range(6):
            require_continuable_child(state, 192)
            state = child_state(state, 192)
            self.assertTrue(tail_fits(state), generation)


class PipelineWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'take.mctx.safetensors'
        self.path.write_bytes(b'header supplied by the bounded index test double')

    def header(self, state):
        return SimpleNamespace(metadata={
            'audio_phase': f'{float(state.audio_phase):.6f}',
            'raw_frames': str(state.raw_frames),
            'pinned_head_frames': str(state.pinned_head),
            'delivered_frames': str(state.delivered_frames)},
            tensors={'audio': SimpleNamespace(shape=(1, 32, 2, state.audio_ticks))})

    def test_submit_refuses_a_dead_end_length_before_upload(self):
        # A clean 362-frame root is continuable today, but a 362-frame child of it
        # freezes phase -1/3 and could never be continued again.
        saved = SimpleNamespace(artifacts=context_family(362, 362), mctx=self.path)
        client, inventory = Mock(), Mock()
        with patch.object(pipeline, 'get_validated_family', return_value=saved), \
             patch('h3_av_state.read_safetensors_header',
                   return_value=self.header(AVState(362, 0, 362, audio_ticks(362), Fraction(0)))):
            with self.assertRaises(UncontinuableLength):
                pipeline.submit_forward('/work', TAKE.take_id,
                    SimpleNamespace(prompt='Continue the shot', raw_frames=362, seed=7),
                    client=client, models=MODELS,
                    references=[{'__type': 'core/ASSET', 'info': {'id': 'ref'}}],
                    target_fingerprint='f'*64, work_root='/ops', inventory=inventory)
        client.assets.from_file.assert_not_called()
        client.run.assert_not_called()
        inventory.assert_not_called()

    def test_preflight_reports_the_dead_end_before_any_inventory_call(self):
        saved = SimpleNamespace(artifacts=context_family(158, 123), mctx=self.path)
        inventory = Mock()
        with patch.object(pipeline, 'get_validated_family', return_value=saved), \
             patch('h3_av_state.read_safetensors_header', return_value=self.header(PARENT_DEAD)):
            with self.assertRaises(AVStateError):
                pipeline.preflight_continuation('/work', TAKE.take_id, models=MODELS,
                    direction='Continue the shot', reference_count=1,
                    raw_frames=158, inventory=inventory)
        inventory.assert_not_called()

    def test_readiness_separates_integrity_from_continuability(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import continuable_take_api as api
        saved = SimpleNamespace(mctx=self.path, record=SimpleNamespace(to_manifest=lambda: {
            'family': {'context': {'delivered_frames': 123, 'fps': 24}}}))
        app = FastAPI()
        app.include_router(api.create_router(lambda: Path('/work')))
        with patch.object(api, 'get_take', return_value=TAKE), \
             patch.object(api, 'get_validated_family', return_value=saved), \
             patch('h3_av_state.read_safetensors_header', return_value=self.header(PARENT_DEAD)):
            body = TestClient(app).get(
                '/api/continuity/takes/' + TAKE.take_id + '/readiness').json()
        self.assertEqual(body['verified'], True)
        self.assertEqual(body['extend'], False)
        self.assertIn('cannot be continued', body['reason'])

    def test_attempts_endpoint_refuses_before_a_worker_starts(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import continuity_attempt_api as api
        worker = Mock()
        app = FastAPI()
        app.include_router(api.create_router(
            lambda: Path(self.temp.name), worker=worker,
            precheck=lambda take_id, raw: pipeline.precheck_request('/work', take_id, raw)))
        saved = SimpleNamespace(artifacts=context_family(362, 362), mctx=self.path)
        with patch.object(pipeline, 'get_validated_family', return_value=saved), \
             patch('h3_av_state.read_safetensors_header',
                   return_value=self.header(AVState(362, 0, 362, audio_ticks(362), Fraction(0)))):
            response = TestClient(app).post(
                '/api/continuity/takes/' + TAKE.take_id + '/attempts',
                json={'request_id': 'a'*32, 'prompt': 'Keep walking', 'raw_frames': 362,
                      'seeds': [7]})
        self.assertEqual(response.status_code, 422)
        self.assertIn('not submitted', response.json()['detail'])
        worker.start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
