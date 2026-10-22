"""A Take is only a parent if its measured range can carry the pin window."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_pipeline as pipeline  # noqa: E402
from continuity_pipeline import native_parent  # noqa: E402
from h3_continuity_graphs import H3ContinuityModels, PIN_WINDOW, Weight  # noqa: E402

MODELS = H3ContinuityModels(
    unet=Weight('minimax_h3_fl2va_pruned_int8_convrot.safetensors'),
    clip=Weight('qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'),
    video_vae=Weight('minimax_h3_video_vae_fp16.safetensors'),
    audio_vae=Weight('minimax_h3_audio_vae_fp32.safetensors'))


def family(delivered=56, fps=24.0, width=1280, height=704):
    manifest = {'context': {'format': 'mctx_v1', 'width': width, 'height': height,
                            'fps': fps, 'raw_frames': 56, 'delivered_frames': delivered}}
    return SimpleNamespace(to_manifest=lambda: manifest)


TAKE = SimpleNamespace(take_id='a' * 32, capsule_sha256='b' * 64)


class NativeParentTests(unittest.TestCase):
    def test_builds_attestation_from_measured_context_not_from_names(self):
        parent = native_parent(TAKE, family(), models=MODELS,
                               clip='opengenjutsu_continuity/x/take.mp4')
        self.assertEqual(parent.take_id, TAKE.take_id)
        self.assertEqual((parent.width, parent.height, parent.fps), (1280, 704, 24))
        self.assertEqual(parent.delivered_frames, 56)
        self.assertEqual(parent.capsule_digest, TAKE.capsule_sha256)
        self.assertEqual(parent.clip, 'opengenjutsu_continuity/x/take.mp4')

    def test_refuses_a_take_too_short_to_carry_the_pin_window(self):
        # 21 delivered frames is exactly what a 39-frame tail pin produces; it
        # cannot be used as the next parent without inventing context.
        with self.assertRaisesRegex(ValueError, f'at least {PIN_WINDOW}'):
            native_parent(TAKE, family(delivered=PIN_WINDOW - 1), models=MODELS, clip='x/take.mp4')

    def test_refuses_a_non_24fps_take(self):
        with self.assertRaisesRegex(ValueError, '24 fps'):
            native_parent(TAKE, family(fps=25.0), models=MODELS, clip='x/take.mp4')

    def test_refuses_an_incomplete_model_profile(self):
        with self.assertRaisesRegex(ValueError, 'model profile'):
            native_parent(TAKE, family(), models={'unet': Weight('a.safetensors')},
                          clip='x/take.mp4')


class SubmitForwardOrderingTests(unittest.TestCase):
    """A refused parent must cost nothing: no upload, no submission."""

    def request(self):
        return SimpleNamespace(prompt='continue', seed=7, raw_frames=124,
                               request_id='c' * 32)

    def submit(self, client, delivered=56, fps=24.0):
        with patch.object(pipeline, 'get_validated_family', return_value=family(delivered, fps)), \
                patch.object(pipeline, 'get_take', return_value=TAKE):
            return pipeline.submit_forward(
                '/work', TAKE.take_id, self.request(), client=client, models=MODELS,
                references=[{'__type': 'core/ASSET', 'info': {'id': 'ref'}}],
                target_fingerprint='f' * 64, work_root='/operations')

    def test_a_take_below_the_pin_window_costs_no_upload_and_no_submission(self):
        client = MagicMock()
        with self.assertRaisesRegex(ValueError, f'at least {PIN_WINDOW}'):
            self.submit(client, delivered=PIN_WINDOW - 1)
        client.assets.from_file.assert_not_called()
        client.run.assert_not_called()
        client.submit.assert_not_called()

    def test_a_non_24fps_take_is_refused_before_any_client_call(self):
        client = MagicMock()
        with self.assertRaisesRegex(ValueError, '24 fps'):
            self.submit(client, fps=30.0)
        client.run.assert_not_called()

    def test_an_unreadable_family_never_reaches_the_target(self):
        client = MagicMock()
        with patch.object(pipeline, 'get_validated_family',
                          side_effect=ValueError('Frozen Take evidence differs')):
            with self.assertRaises(ValueError):
                pipeline.submit_forward(
                    '/work', TAKE.take_id, self.request(), client=client, models=MODELS,
                    references=[{'__type': 'core/ASSET', 'info': {'id': 'ref'}}],
                    target_fingerprint='f' * 64, work_root='/operations')
        client.assets.from_file.assert_not_called()
        client.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()


class ParentContextShapeTests(unittest.TestCase):
    """The validated wrapper, not only the raw artifact set, must be accepted."""

    def test_a_validated_family_wrapper_is_read_through_its_artifacts(self):
        import continuity_pipeline as pipeline
        import types

        measured = types.SimpleNamespace(to_manifest=lambda: {'context': {
            'width': 960, 'height': 544, 'delivered_frames': 157, 'fps': 24}})
        wrapper = types.SimpleNamespace(artifacts=measured)
        context = pipeline.parent_context(wrapper)
        self.assertEqual(context['delivered_frames'], 157)

    def test_a_short_parent_is_still_refused_through_the_wrapper(self):
        import continuity_pipeline as pipeline
        import types

        measured = types.SimpleNamespace(to_manifest=lambda: {'context': {
            'width': 960, 'height': 544, 'delivered_frames': 20, 'fps': 24}})
        with self.assertRaisesRegex(ValueError, 'tail pin'):
            pipeline.parent_context(types.SimpleNamespace(artifacts=measured))


class RestageNamingTests(unittest.TestCase):
    """The upload name is chosen by the application, never by the target's dedup."""

    def test_uploads_use_the_unique_family_name_and_leave_the_source_intact(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        import continuity_pipeline as pipeline
        import types

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video, mctx, cond = root / 'take.mp4', root / 'take.mctx.safetensors', root / 'take.cond.safetensors'
            for path, data in ((video, b'V'), (mctx, b'M'), (cond, b'C')):
                path.write_bytes(data)
            artifacts = types.SimpleNamespace(video=video, mctx=mctx, conditioning=cond)
            seen = []
            client = MagicMock()
            client.assets.from_file.side_effect = lambda p: seen.append(Path(p).name) or types.SimpleNamespace(
                as_reference=lambda: {'__type': 'core/ASSET', 'info': {'id': 'x'}})
            client.run.return_value = types.SimpleNamespace(status='succeeded')
            client.workflows.from_json.side_effect = lambda graph: graph
            with patch.object(pipeline, 'read_clip_handle', return_value='opengenjutsu/x/take.mp4'):
                pipeline.restage_parent(client, artifacts, 'a' * 32)
            self.assertEqual(seen, ['a' * 32 + '.mp4', 'a' * 32 + '.mctx.safetensors',
                                    'a' * 32 + '.cond.safetensors'])
            self.assertEqual(video.read_bytes(), b'V', 'the stored family is copied, never renamed')
