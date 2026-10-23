"""Known bad saved boundaries must fail before upload, refiner or sampling."""
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import Mock, patch

import continuity_pipeline as pipeline
from h3_audio_boundary import IncompatibleAudioBoundary, MESSAGE, require_complete_masked_tail
from test_continuity_pipeline import family, MODELS, TAKE


def header(*, ticks=263, phase='-0.333333', raw=158, head=35, delivered=123):
    return SimpleNamespace(metadata={'audio_phase': phase, 'raw_frames': str(raw),
        'pinned_head_frames': str(head), 'delivered_frames': str(delivered)},
        tensors={'audio': SimpleNamespace(shape=(1, 32, 2, ticks))})


class AudioBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'take.mctx.safetensors'
        self.path.write_bytes(b'header supplied by the bounded index test double')

    def test_real_parent_coordinates_refuse_without_mutating_header(self):
        h = header()
        original = dict(h.metadata)
        with self.assertRaises(IncompatibleAudioBoundary) as e:
            require_complete_masked_tail(h)
        self.assertEqual(str(e.exception), MESSAGE)
        self.assertEqual(h.metadata, original)

    def test_complete_windows_and_non_finite_phase(self):
        require_complete_masked_tail(header(phase='0'))
        require_complete_masked_tail(header(ticks=264))
        for phase in ('NaN', 'Infinity', 'not-a-number'):
            with self.assertRaises(IncompatibleAudioBoundary):
                require_complete_masked_tail(header(phase=phase))

    def test_phase_aware_runtime_refusal_precedes_inventory_or_client_work(self):
        saved = SimpleNamespace(artifacts=family(), mctx=self.path)
        inventory = Mock(side_effect=AssertionError("inventory reached before boundary refusal"))
        with patch.object(pipeline, 'get_validated_family', return_value=saved), \
             patch('h3_audio_boundary.read_safetensors_header', return_value=header()):
            with self.assertRaises(IncompatibleAudioBoundary):
                pipeline.preflight_continuation('/work', TAKE.take_id, models=MODELS,
                    direction='Continue the shot', reference_count=1, inventory=inventory)
        inventory.assert_not_called()

    def test_readiness_preserves_verified_state_but_refuses_extend(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import continuable_take_api as api
        saved = SimpleNamespace(mctx=self.path, record=SimpleNamespace(to_manifest=lambda: {
            'family': {'context': {'delivered_frames': 123, 'fps': 24}}}))
        app = FastAPI()
        app.include_router(api.create_router(lambda: Path('/work')))
        with patch.object(api, 'get_take', return_value=TAKE), \
             patch.object(api, 'get_validated_family', return_value=saved), \
             patch('h3_audio_boundary.read_safetensors_header', return_value=header()):
            response = TestClient(app).get('/api/continuity/takes/' + TAKE.take_id + '/readiness')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'verified': True, 'extend': False, 'reason': MESSAGE})

    def test_direct_submit_cannot_bypass_the_boundary_refusal(self):
        saved = SimpleNamespace(artifacts=family(), mctx=self.path)
        client, inventory = Mock(), Mock(side_effect=AssertionError("inventory reached before boundary refusal"))
        with patch.object(pipeline, 'get_validated_family', return_value=saved), \
             patch('h3_audio_boundary.read_safetensors_header', return_value=header()):
            with self.assertRaises(IncompatibleAudioBoundary):
                pipeline.submit_forward('/work', TAKE.take_id,
                    SimpleNamespace(prompt='Continue the shot', raw_frames=158, seed=7),
                    client=client, models=MODELS, references=[{'__type': 'core/ASSET', 'info': {'id': 'ref'}}],
                    target_fingerprint='f'*64, work_root='/ops', inventory=inventory)
        client.assets.from_file.assert_not_called()
        client.run.assert_not_called()
        client.submit.assert_not_called()
        inventory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
