"""A Take is only a parent if its measured range can carry the pin window."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
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


if __name__ == '__main__':
    unittest.main()
