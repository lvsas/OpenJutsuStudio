"""Every binding of the adopted template is applied, or the compile fails."""
import json
import sys
from dataclasses import dataclass
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import h3_latent_graphs as latent  # noqa: E402

OP = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
REF1 = {'__type': 'core/ASSET', 'info': {'id': 'ref-one'}}
REF2 = {'__type': 'core/ASSET', 'info': {'id': 'ref-two'}}


@dataclass(frozen=True)
class W:
    filename: str


@dataclass(frozen=True)
class M:
    unet: W
    clip: W
    video_vae: W
    audio_vae: W


MODELS = M(W('unet.safetensors'), W('clip.safetensors'), W('v.safetensors'), W('a.safetensors'))


def build(**over):
    args = dict(references=[REF1], prompt='Continue this shot: she walks.', width=1280,
                height=704, raw_frames=158, seed=42, models=MODELS,
                parent_clip='genjutsu/take.mp4', operation_id=OP)
    args.update(over)
    return latent.build_latent_continuity(**args)


class LatentGraphTests(unittest.TestCase):
    def test_the_template_is_not_mutated_between_compiles(self):
        before = latent.TEMPLATE.read_text()
        build()
        self.assertEqual(latent.TEMPLATE.read_text(), before)

    def test_weights_prompt_seed_parent_and_output_are_bound(self):
        g = build()
        self.assertEqual(g['725']['inputs']['unet_name'], 'unet.safetensors')
        self.assertEqual(g['752:747']['inputs']['clip_name'], 'clip.safetensors')
        self.assertEqual(g['752:748']['inputs']['vae_name'], 'v.safetensors')
        self.assertEqual(g['752:798']['inputs']['vae_name'], 'a.safetensors')
        self.assertEqual(g['761:763']['inputs']['value'], 'Continue this shot: she walks.')
        self.assertEqual(g['2004']['inputs']['value'], 42)
        self.assertEqual(g['2010']['inputs']['clip'], 'genjutsu/take.mp4')
        self.assertEqual(g['761:1217']['inputs']['value'],
                         f'OpenGenjutsu/continuity/takes/{OP}')

    def test_geometry_is_the_parent_size_not_a_derived_aspect_ratio(self):
        g = build(width=1312, height=736)
        self.assertEqual(g['761:1381']['inputs']['in_2'], ['bound_width', 0])
        self.assertEqual(g['761:1381']['inputs']['in_3'], ['bound_height', 0])
        self.assertEqual(g['bound_width']['inputs']['value'], 1312)
        self.assertEqual(g['bound_height']['inputs']['value'], 736)
        self.assertNotEqual(g['761:1381']['inputs']['in_2'][0], '761:1086')

    def test_one_loader_per_reference_in_order(self):
        g = build(references=[REF1, REF2])
        self.assertEqual(g['797']['inputs']['ref_images.ref_image_0'], ['ref_image_0', 0])
        self.assertEqual(g['797']['inputs']['ref_images.ref_image_1'], ['ref_image_1', 0])
        self.assertEqual(g['ref_image_0']['inputs']['image'], REF1)
        self.assertEqual(g['ref_image_1']['inputs']['image'], REF2)

    def test_duration_is_expressed_so_the_grid_expression_returns_the_frames(self):
        g = build(raw_frames=158)
        seconds = g['2001']['inputs']['value']
        self.assertAlmostEqual(seconds * 24, 158)

    def test_a_reference_must_be_a_committed_asset(self):
        with self.assertRaisesRegex(ValueError, 'committed SDK asset'):
            build(references=['/home/user/ref.png'])

    def test_an_incomplete_model_profile_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'model profile'):
            build(models=M(W(''), W('c'), W('v'), W('a')))

    def test_bad_identifiers_and_geometry_are_refused(self):
        for over in ({'operation_id': '../escape'}, {'width': 0}, {'height': True},
                     {'raw_frames': 0}, {'seed': -1}, {'seed': True},
                     {'prompt': ' '}, {'references': []}, {'publish_family': 'yes'}):
            with self.subTest(over=list(over)), self.assertRaises(ValueError):
                build(**over)

    def test_publication_consumes_the_saver_clip_and_exposes_a_handle(self):
        g = build(publish_family=True)
        self.assertEqual(g['native_family']['class_type'], 'OpenGenjutsuH3PublishClip')
        self.assertEqual(g['native_family']['inputs']['clip'], ['1216', 0])
        self.assertEqual(g['native_clip_handle']['inputs']['text'], ['native_family', 0])
        self.assertIn(OP, g['native_clip_handle']['inputs']['filename_prefix'])

    def test_dormant_host_style_loras_are_not_compiled(self):
        g = build(publish_family=True)
        loras = {n: i['inputs'].get('lora_name') for n, i in g.items()
                 if i.get('class_type') == 'LoraLoaderModelOnly'}
        self.assertEqual(loras, {'1334:1319': ['1334:1330', 3]},
                         'only the bundle-driven loader may survive; style LoRAs are gone')
        literals = [value for node in g.values()
                    for value in (node.get('inputs') or {}).values()
                    if isinstance(value, str) and value.endswith('.safetensors')
                    and 'lora' in (node.get('class_type') or '').lower()]
        self.assertEqual([], literals, 'no style adapter may be named literally')

    def test_every_literal_switch_is_compiled_away(self):
        g = build()
        for node_id, node in g.items():
            if node.get('class_type') != 'ComfySwitchNode':
                continue
            source = g.get(node['inputs']['switch'][0], {})
            self.assertNotEqual(source.get('class_type'), 'PrimitiveBoolean',
                                f'{node_id} still selects on a literal boolean')

    def test_collapsing_the_switches_keeps_the_model_chain_connected(self):
        g = build()
        self.assertIn('725', g)
        # The UNET must still reach a consumer, and no reference may dangle.
        consumers = [n for n, node in g.items() for ref in node['inputs'].values()
                     if isinstance(ref, list) and ref and ref[0] == '725']
        self.assertTrue(consumers, 'the UNET became unreachable')
        for node_id, node in g.items():
            for field, ref in node['inputs'].items():
                if isinstance(ref, list) and len(ref) == 2 and isinstance(ref[0], str):
                    self.assertIn(ref[0], g, f'{node_id}.{field} points at a removed node')

    def test_publication_is_absent_unless_requested(self):
        g = build()
        self.assertNotIn('native_family', g)
        self.assertNotIn('native_clip_handle', g)


if __name__ == '__main__':
    unittest.main()
