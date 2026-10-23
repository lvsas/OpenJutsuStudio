"""Every binding of the adopted template is applied, or the compile fails."""
import copy
import hashlib
import json
import sys
from unittest import mock
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


class BoundedTopologyTests(unittest.TestCase):
    def verify(self, graph, mode='forward', second_parent_clip=None):
        latent._verify(graph, 1280, 704, 158, 42, 'Continue this shot: she walks.',
                       [REF1], OP, mode=mode, parent_clip='genjutsu/take.mp4',
                       second_parent_clip=second_parent_clip)

    def test_forward_bytes_match_pre_change_compiler(self):
        # SHA256(json.dumps(graph, allow_nan=False)) captured by executing
        # git show 578109c:src/h3_latent_graphs.py, not the modified compiler.
        fixtures = [
            (1, False, 158, 42, 1280, 704,
             'bad3a3a53cb47b700f4388308b8a2bc6aab6027ac8ae82711ef99489b1864c0c'),
            (2, True, 362, 2**64 - 1, 1312, 736,
             '35ceffe2fb92b39907125d919312c005c3481503aa2a63130db6d8bbe68aa67c'),
            (3, False, 56, 0, 704, 1280,
             '318dab743e0c7efd2c97a0e44b38c68b8f294ba9478cb96727f260c578b480da'),
        ]
        for count, publish, frames, seed, width, height, digest in fixtures:
            refs = [{'__type': 'core/ASSET', 'info': {'id': f'ref-{i}'}}
                    for i in range(count)]
            args = dict(references=refs, publish_family=publish, raw_frames=frames,
                        seed=seed, width=width, height=height)
            implicit = json.dumps(build(**args), allow_nan=False).encode()
            explicit = json.dumps(build(mode='forward', **args), allow_nan=False).encode()
            with self.subTest(count=count):
                self.assertEqual(implicit, explicit)
                self.assertEqual(hashlib.sha256(implicit).hexdigest(), digest)

    def test_prepend_only_changes_the_existing_pin_anchor(self):
        expected = build()
        expected['2020']['inputs'].update(take_from='head', place='after')
        actual = build(mode='prepend')
        self.assertEqual(actual, expected)
        self.assertNotIn('2011', actual)
        self.assertNotIn('2021', actual)

    def test_bridge_only_clones_and_chains_the_second_parent_pair(self):
        expected = build(references=[REF1, REF2], publish_family=True)
        expected['2011'] = copy.deepcopy(expected['2010'])
        expected['2011']['inputs']['clip'] = 'genjutsu/second (1).mp4'
        expected['2021'] = copy.deepcopy(expected['2020'])
        expected['2021']['inputs'].update(mctx=['2011', 3], take_from='head',
                                          place='after', pin_specs=['2020', 0])
        expected['1228']['inputs']['pin_specs'] = ['2021', 0]
        actual = build(mode='bridge', second_parent_clip='genjutsu/second (1).mp4',
                       references=[REF1, REF2], publish_family=True)
        self.assertEqual(actual, expected)

    def test_modes_and_second_handles_fail_closed(self):
        self.assertEqual(latent.MODES, ('forward', 'prepend', 'bridge'))
        for mode in ('reverse', 'backward', 'root', 'Forward', '', None, [], {}):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                build(mode=mode)
        for mode in ('forward', 'prepend'):
            for second in ('genjutsu/b.mp4', '', False, 0):
                with self.subTest(mode=mode, second=second), self.assertRaises(ValueError):
                    build(mode=mode, second_parent_clip=second)
        for second in (None, '', ' ', False, [], 'genjutsu/take.mp4'):
            with self.subTest(second=second), self.assertRaises(ValueError):
                build(mode='bridge', second_parent_clip=second)

    def test_invalid_restaged_handle_literals_are_not_repaired(self):
        for handle in (' ', '../take.mp4', '/take.mp4', 'genjutsu/../take.mp4',
                       'genjutsu//take.mp4', 'bad\n.mp4', 'take.mp4 ', 42):
            for mode in ('forward', 'prepend', 'bridge'):
                with self.subTest(handle=handle, mode=mode), self.assertRaises(ValueError):
                    build(mode=mode, parent_clip=handle,
                          second_parent_clip='genjutsu/b.mp4' if mode == 'bridge' else None)
            with self.subTest(second=handle), self.assertRaises(ValueError):
                build(mode='bridge', second_parent_clip=handle)

    def test_native_grid_and_range_are_checked_without_temporal_claims(self):
        for frames in (True, 4, 6, 157, 159, 3601, 3609):
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                build(raw_frames=frames)
        for frames in (5, 22, 56, 158, 362, 3592):
            self.assertAlmostEqual(build(raw_frames=frames)['2001']['inputs']['value'] * 24,
                                   frames)

    def test_effective_pin_and_loader_drift_is_rejected_in_each_mode(self):
        pin_mutations = dict(mode='guide', mask_hold=1.0, mask_ramp_frames=1,
                             mask_ramp_edge=0.5, window='38', audio_window=1,
                             take_from='frame', take_from_frame=1,
                             place='at_frame', place_at_frame=1, mctx=['2010', 0])
        for mode in latent.MODES:
            second = 'genjutsu/b.mp4' if mode == 'bridge' else None
            base = build(mode=mode, second_parent_clip=second)
            pairs = [('2010', '2020')]
            if second:
                pairs.append(('2011', '2021'))
            for loader, pin in pairs:
                mutations = [(pin, field, value) for field, value in pin_mutations.items()]
                mutations += [(loader, 'create_pins', 'both'), (loader, 'pin_window', '38'),
                              (loader, 'clip', 'genjutsu/wrong.mp4')]
                for node, field, value in mutations:
                    graph = copy.deepcopy(base)
                    graph[node]['inputs'][field] = value
                    with self.subTest(mode=mode, node=node, field=field), self.assertRaises(ValueError):
                        self.verify(graph, mode, second)
            for node in ('2010', '2020', '1228'):
                graph = copy.deepcopy(base)
                graph[node]['class_type'] = 'WrongClass'
                with self.subTest(mode=mode, node=node), self.assertRaises(ValueError):
                    self.verify(graph, mode, second)
            graph = copy.deepcopy(base)
            graph['1228']['inputs']['pin_specs'] = ['2010', 2]
            with self.assertRaises(ValueError):
                self.verify(graph, mode, second)
            if second:
                graph = copy.deepcopy(base)
                graph['2021']['inputs']['pin_specs'] = ['2010', 2]
                with self.assertRaises(ValueError):
                    self.verify(graph, mode, second)

    def test_sampling_save_decode_and_hr_state_flow_cannot_drift(self):
        edges = [
            ('1228', 'conditioning', ['797', 1]), ('1228', 'latent', ['797', 0]),
            ('1488:1483', 'conditioning', ['797', 0]),
            ('1488:1486', 'latent_image', ['797', 1]),
            ('1488:1486', 'guider', ['1359:1311', 0]),
            ('3001', 'latent', ['797', 1]),
            ('1216', 'samples', ['1488:1486', 0]),
            ('1216', 'conditioning', ['797', 0]), ('1216', 'pins', ['2020', 0]),
            ('1216', 'save_conditioning', False), ('1216', 'images', ['751:633', 0]),
            ('751:632', 'samples', ['1488:1486', 0]),
            ('751:633', 'samples', ['1488:1486', 0]),
            ('1349', 'sequence', ['2003', 0]), ('1350', 'av_latent', ['797', 1]),
            ('1351', 'latent', ['1350', 1]), ('1352', 'audio_latent', ['1350', 0]),
            ('1352', 'video_latent', ['1350', 0]), ('1365', 'anything', ['797', 1]),
            ('1363', 'latent', ['797', 1]), ('1362', 'layout', ['1349', 0]),
            ('1359:1311', 'conditioning', ['1228', 0]),
            ('1359:1313', 'latent_image', ['1228', 1]),
            ('1359:1313', 'guider', ['1488:1483', 0]),
            ('1366', 'anything', ['1359:1313', 0]),
            ('1434', 'samples', ['1359:1313', 1]),
            ('1434', 'conditioning', ['1228', 0]), ('1434', 'layout', ['1349', 0]),
        ]
        for mode in latent.MODES:
            second = 'genjutsu/b.mp4' if mode == 'bridge' else None
            base = build(mode=mode, second_parent_clip=second)
            for node, field, value in edges:
                graph = copy.deepcopy(base)
                graph[node]['inputs'][field] = value
                with self.subTest(mode=mode, node=node, field=field), self.assertRaises(ValueError):
                    self.verify(graph, mode, second)

    def test_corrupt_template_is_refused_not_silently_fallback_compiled(self):
        for node, field in [('2010', 'clip'), ('2020', 'place'), ('2020', 'mctx')]:
            template = json.loads(latent.TEMPLATE.read_text())
            del template[node]['inputs'][field]
            with mock.patch.object(latent, 'TEMPLATE') as source:
                source.read_text.return_value = json.dumps(template)
                with self.subTest(node=node, field=field), self.assertRaises(ValueError):
                    build(mode='bridge', second_parent_clip='genjutsu/b.mp4')

    def test_finite_json_and_dangling_links_are_checked(self):
        for mode in latent.MODES:
            second = 'genjutsu/b.mp4' if mode == 'bridge' else None
            base = build(mode=mode, second_parent_clip=second)
            json.dumps(base, allow_nan=False)
            for value in (float('nan'), float('inf'), -float('inf'), ['missing_node', 0],
                          ['2010', -1]):
                graph = copy.deepcopy(base)
                graph['200']['inputs']['probe'] = value
                with self.subTest(mode=mode, value=value), self.assertRaises(ValueError):
                    self.verify(graph, mode, second)

    def test_corrupt_template_state_and_reserved_nodes_fail_before_return(self):
        original = json.loads(latent.TEMPLATE.read_text())
        corruptions = []
        for node in ('2010', '2020', '1228', '1488:1486', '1359:1313'):
            template = copy.deepcopy(original)
            del template[node]
            corruptions.append(template)
        for node, field, value in (
                ('2020', 'mode', 'guide'), ('2010', 'create_pins', 'both'),
                ('1216', 'samples', ['1488:1486', 0]),
                ('200', 'image', ['missing_node', 0]),
                ('200', 'probe', float('nan'))):
            template = copy.deepcopy(original)
            template[node]['inputs'][field] = value
            corruptions.append(template)
        for node, source_node in (('2011', '2010'), ('2021', '2020'),
                                  ('unexpected_pin', '2020')):
            template = copy.deepcopy(original)
            template[node] = copy.deepcopy(template[source_node])
            corruptions.append(template)
        for index, template in enumerate(corruptions):
            for mode in latent.MODES:
                with mock.patch.object(latent, 'TEMPLATE') as source:
                    source.read_text.return_value = json.dumps(template)
                    with self.subTest(index=index, mode=mode), self.assertRaises(ValueError):
                        build(mode=mode, second_parent_clip='genjutsu/b.mp4' if mode == 'bridge' else None)

    def test_multiple_references_and_publication_keep_the_same_dependencies(self):
        refs = [{'__type': 'core/ASSET', 'info': {'id': f'ordered-{i}'}}
                for i in range(5)]
        baseline = build(references=refs, publish_family=True)
        classes = {node['class_type'] for node in baseline.values()}
        for mode in latent.MODES:
            graph = build(mode=mode, second_parent_clip='genjutsu/b.mp4' if mode == 'bridge' else None,
                          references=refs, publish_family=True)
            self.assertEqual({node['class_type'] for node in graph.values()}, classes)
            for index, reference in enumerate(refs):
                self.assertEqual(graph['797']['inputs'][f'ref_images.ref_image_{index}'],
                                 [f'ref_image_{index}', 0])
                self.assertEqual(graph[f'ref_image_{index}']['inputs']['image'], reference)
            for node in ('native_family', 'native_clip_handle', '725', '752:747',
                         '752:748', '752:798', '1351'):
                self.assertEqual(graph[node], baseline[node])

    def test_bridge_and_prepend_do_not_leak_into_later_forward_compiles(self):
        baseline = build()
        before = latent.TEMPLATE.read_bytes()
        for mode in ('bridge', 'prepend'):
            graph = build(mode=mode, second_parent_clip='genjutsu/b.mp4' if mode == 'bridge' else None)
            graph['2020']['inputs']['mask_hold'] = 0.8
            self.assertEqual(build(), baseline)
            self.assertEqual(latent.TEMPLATE.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
