"""Native continuity contracts only: no submission, tensor import or rendering.

All asset IDs and weight hashes below are unit fixtures, not execution evidence.
"""
import copy
from dataclasses import FrozenInstanceError, replace
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import h3_continuity_graphs as h3


class ContinuityGraphTests(unittest.TestCase):
    def models(self):
        return h3.H3ContinuityModels(
            unet=h3.Weight('minimax_h3_ref2va_pruned_int8_convrot.safetensors', '1' * 64),
            clip=h3.Weight('qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors', '2' * 64),
            video_vae=h3.Weight('minimax_h3_video_vae_fp16.safetensors', '3' * 64),
            audio_vae=h3.Weight('minimax_h3_audio_vae_fp32.safetensors', '4' * 64))

    def parent(self, take='parent-a', family='a'):
        return h3.NativeH3Parent(take_id=take,
            clip=f'opengenjutsu_continuity/{family * 32}/take.mp4',
            width=960, height=544, delivered_frames=157, fps=24,
            models=self.models(), capsule_digest=family * 64)

    def build(self, mode='root', **kwargs):
        opts: dict = dict(operation_id='c' * 32, seed=8801, width=960, height=544,
                    raw_frames=192, models=self.models(), parents=())
        if mode in ('forward', 'reverse'):
            opts['parents'] = (self.parent(),)
        elif mode == 'bridge':
            opts['parents'] = (self.parent(), self.parent('parent-b', 'b'))
        opts.update(kwargs)
        return h3.build_h3_continuity(mode,
            {'__type': 'core/ASSET', 'info': {'id': 'unit-character-reference'}},
            '  A character walks.\nKeep this prompt intact.  ', **opts)

    def test_root_consumes_one_committed_character_and_verbatim_prompt(self):
        recipe = self.build(); graph = recipe.graph
        loaders = [k for k, v in graph.items() if v['class_type'] == 'LoadImage']
        self.assertEqual(loaders, ['200'])
        self.assertEqual(graph['200']['inputs']['image'],
            {'__type': 'core/ASSET', 'info': {'id': 'unit-character-reference'}})
        self.assertEqual(graph['761:763']['inputs']['value'],
                         '  A character walks.\nKeep this prompt intact.  ')
        self.assertEqual(graph['1383']['inputs']['in_3'], ['200', 0])
        self.assertEqual(graph['1392']['inputs']['names'], 'ref_image_0\nref_audio_0\nref_audio_1')
        self.assertEqual(graph['797']['inputs']['ref_images.ref_image_0'], ['1392', 0])
        self.assertEqual(graph['797']['inputs']['prompt'], ['1390', 0])
        self.assertEqual(graph['1390']['inputs']['in'], ['761:1381', 0])
        self.assertEqual(graph['761:1381']['inputs']['in_1'], ['761:763', 0])
        self.assertNotIn('pin_specs', graph['1228']['inputs'])
        self.assertFalse(any(v['class_type'] == 'H3LoadVideoWithMCtx' for v in graph.values()))

    def test_native_saver_uses_actual_sampled_slot_conditioning_and_pins(self):
        for mode in ('root', 'forward', 'reverse', 'bridge'):
            with self.subTest(mode=mode):
                g = self.build(mode).graph
                self.assertEqual(g['1488:1486']['inputs']['latent_image'], ['1228', 1])
                self.assertEqual(g['1488:1483']['inputs']['conditioning'], ['1228', 0])
                for node in ('1216', '751:632', '751:633'):
                    self.assertEqual(g[node]['inputs']['samples'], ['1488:1486', 1])
                self.assertEqual(g['1216']['inputs']['conditioning'], ['1228', 0])
                self.assertEqual(g['1216']['inputs']['pins'], ['1228', 2])
                self.assertIs(g['1216']['inputs']['save_conditioning'], True)
                self.assertEqual(g['1216']['inputs']['images'], ['751:632', 0])
                self.assertEqual(g['1216']['inputs']['audio'], ['751:633', 0])
                self.assertEqual(g[h3.HANDLE_NODE]['inputs']['text'], ['1216', 0])
                self.assertEqual(g[h3.HANDLE_NODE]['inputs']['format'], 'txt')
                self.assertNotIn('VHS_VideoCombine', {n['class_type'] for n in g.values()})
                self.assertFalse(self.build(mode).as_dict()['publication']['family_assets_published'])

    def test_parent_anchor_direction_and_bridge_stack(self):
        for mode, source, place in (('forward', 'tail', 'before'), ('reverse', 'head', 'after')):
            g = self.build(mode).graph
            self.assertEqual(g['2020']['inputs']['take_from'], source)
            self.assertEqual(g['2020']['inputs']['place'], place)
            self.assertEqual(g['2020']['inputs']['mctx'], ['2010', 3])
            self.assertEqual(g['2010']['inputs']['clip'], self.parent().clip)
            self.assertIsInstance(g['2010']['inputs']['clip'], str)  # Native filename COMBO.
            self.assertEqual(g['1228']['inputs']['pin_specs'], ['2020', 0])
            self.assertNotIn('2021', g)
        g = self.build('bridge').graph
        self.assertEqual((g['2020']['inputs']['take_from'], g['2020']['inputs']['place']), ('tail', 'before'))
        self.assertEqual((g['2021']['inputs']['take_from'], g['2021']['inputs']['place']), ('head', 'after'))
        self.assertEqual(g['2021']['inputs']['mctx'], ['2011', 3])
        self.assertEqual(g['2021']['inputs']['pin_specs'], ['2020', 0])
        self.assertEqual(g['1228']['inputs']['pin_specs'], ['2021', 0])
        self.assertEqual(g['2011']['inputs']['clip'], self.parent('parent-b', 'b').clip)
        self.assertIs(g['1228']['inputs']['snap_window_down_to_available'], False)
        for node in ('2020', '2021'):
            self.assertEqual(g[node]['inputs']['window'], '39')
            self.assertEqual(g[node]['inputs']['mask_hold'], 0.0)

    def test_all_effective_weights_and_sampling_controls_are_consumed(self):
        r = self.build(seed=2**64 - 1); g = r.graph
        for node, key, role in (('725', 'unet_name', 'unet'), ('752:747', 'clip_name', 'clip'),
                                ('752:748', 'vae_name', 'video_vae'), ('752:798', 'vae_name', 'audio_vae')):
            weight = getattr(self.models(), role)
            self.assertEqual(g[node]['inputs'][key], weight.filename)
            self.assertEqual(r.as_dict()['models'][role]['sha256'], weight.sha256)
        self.assertEqual(g['1334:1326']['inputs']['input'], ['725', 0])
        self.assertEqual(g['1488:1483']['inputs']['model'], ['1517', 0])
        self.assertEqual(g['1488:1484']['inputs']['model'], ['1517', 0])
        self.assertEqual(g['1517']['inputs']['model'], ['1334:1519', 0])
        self.assertEqual(g['1488:1482']['inputs']['noise_seed'], ['2004', 0])
        self.assertEqual(g['2004']['inputs']['value'], 2**64 - 1)
        self.assertNotIn('765', g)  # Installed SeedNode narrows uint64 to signed int64.
        self.assertEqual(g['1449']['inputs']['in_1'], 192)
        self.assertEqual(g['761:1381']['inputs']['in_2'], 960)
        self.assertEqual(g['761:1381']['inputs']['in_3'], 544)
        values = json.loads(g['1290']['inputs']['values'])
        self.assertEqual((values['steps'], values['sampler'], values['scheduler']), (20, 'res_multistep', 'simple'))
        self.assertEqual((values['shift_video'], values['shift_audio']), (12, 3))
        self.assertFalse(any('Lora' in n['class_type'] or 'LoRA' in n['class_type'] for n in g.values()))
        self.assertEqual({k for k, n in g.items() if n['class_type'] in ('UNETLoader', 'CLIPLoader', 'VAELoader')},
                         {'725', '752:747', '752:748', '752:798'})
        h3.validate_consumed_links(g)

    def test_recipe_is_immutable_deterministic_and_includes_lineage(self):
        recipe = self.build('bridge'); before = recipe.as_dict()
        graph = recipe.graph; graph['1216']['inputs']['save_conditioning'] = False
        record = recipe.as_dict(); record['models']['unet']['filename'] = 'changed'
        self.assertEqual(recipe.as_dict(), before)
        with self.assertRaises(FrozenInstanceError): recipe.canonical_json = '{}'
        self.assertEqual(recipe.digest, self.build('bridge').digest)
        self.assertNotEqual(recipe.digest, self.build('bridge', seed=8802).digest)
        self.assertEqual(before['source_graph_digest'], h3.SOURCE_GRAPH_DIGEST)
        self.assertEqual(before['parents'][0]['take_id'], 'parent-a')
        self.assertEqual(before['anchors'], [
            {'parent_index': 0, 'take_from': 'tail', 'place': 'before', 'window': 39},
            {'parent_index': 1, 'take_from': 'head', 'place': 'after', 'window': 39}])
        self.assertEqual(before['geometry'], {'width': 960, 'height': 544, 'raw_frames': 192, 'fps': 24})
        self.assertNotIn('delivered_frames', before['geometry'])
        self.assertEqual(before['graph'], recipe.graph)
        self.assertEqual(before['graph_digest'], h3.canonical_digest(recipe.graph))
        metadata = json.loads(recipe.graph['1216']['inputs']['metadata'])
        self.assertEqual(metadata['models'], before['models'])
        self.assertEqual(metadata['anchors'], before['anchors'])

    def test_parent_count_geometry_model_and_state_metadata_are_required(self):
        p = self.parent()
        bad = [('root', (p,)), ('forward', ()), ('reverse', (p, p)), ('bridge', (p,)),
               ('bridge', (p, p)), ('forward', (replace(p, width=512),)),
               ('forward', (replace(p, fps=30),)), ('forward', (replace(p, delivered_frames=38),)),
               ('forward', (replace(p, capsule_digest=''),)),
               ('forward', (replace(p, models=replace(self.models(), unet=h3.Weight('different.safetensors', '5'*64))),)),
               ('forward', (replace(p, clip='../outside.mp4'),)),
               ('forward', (replace(p, clip='/absolute.mp4'),)),
               ('forward', (replace(p, clip='asset-id-not-a-loader-literal'),))]
        for mode, parents in bad:
            with self.subTest(mode=mode, parents=parents), self.assertRaises(ValueError):
                self.build(mode, parents=parents)
        with self.assertRaises(ValueError): self.build('bridge', raw_frames=73)

    def test_invalid_controls_refs_paths_and_seeds_fail_closed(self):
        for kwargs in ({'seed': -1}, {'seed': 2**64}, {'seed': True}, {'raw_frames': 193},
                       {'raw_frames': 0}, {'raw_frames': 3601}, {'width': 961}, {'height': True},
                       {'operation_id': '../escape'}, {'operation_id': 'C'*32}, {'models': None}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.build(**kwargs)
        for ref in (None, '', 'input/file.png', [], [{'__type':'core/ASSET','info':{'id':'one'}}],
                    {'type': 'core/ASSET', 'info': {'id': 'wrong-tag'}},
                    {'__type': 'core/ASSET', 'info': {'id': '../bad'}}):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                h3.build_h3_continuity('root', ref, 'prompt', operation_id='c'*32,
                    width=960, height=544, raw_frames=192, seed=1, models=self.models())
        for mode, prompt in (('invalid', 'prompt'), ('root', ''), ('root', ' \n ')):
            with self.assertRaises(ValueError):
                h3.build_h3_continuity(mode, {'__type':'core/ASSET','info':{'id':'unit'}}, prompt,
                    operation_id='c'*32, width=960, height=544, raw_frames=192, seed=1, models=self.models())
        bad_models = replace(self.models(), video_vae=h3.Weight('../escape', 'invalid'))
        with self.assertRaises(ValueError): self.build(models=bad_models)

    def test_tampered_fixture_and_corrupted_consumed_links_are_rejected(self):
        original = h3.TEMPLATE.read_text()
        changed = json.loads(original)
        changed['1488:1486']['inputs']['latent_image'] = ['797', 1]
        with patch.object(Path, 'read_text', return_value=json.dumps(changed)):
            with self.assertRaisesRegex(ValueError, 'template.*digest'): self.build()
        for node, key, value in (('1216', 'samples', ['1488:1486', 0]),
                                  ('1216', 'conditioning', ['797', 0]),
                                  ('1488:1486', 'latent_image', ['797', 1]),
                                  ('1383', 'in_3', ['missing', 0]),
                                  ('1488:1483', 'model', ['725', 0])):
            graph = self.build().graph; graph[node]['inputs'][key] = value
            with self.subTest(node=node, key=key), self.assertRaises(ValueError):
                h3.validate_consumed_links(graph)

    def test_no_orphan_nodes_sentinels_private_inputs_or_non_native_output(self):
        for mode in ('root', 'forward', 'reverse', 'bridge'):
            g = self.build(mode).graph
            self.assertFalse(h3.unconsumed_nodes(g))
            self.assertNotIn('__H3_BIND_', json.dumps(g))
            output = self.build(mode).as_dict()['publication']
            self.assertEqual(output['saver_node'], '1216')
            self.assertEqual(output['clip_output_slot'], 0)
            self.assertEqual(output['handle_node'], h3.HANDLE_NODE)
            self.assertTrue(output['requires_verified_family_publication'])
        text = h3.TEMPLATE.read_text()
        for forbidden in ('192.168.', 'CharSheet_', 'chouxa', 'Calliope-h3'):
            self.assertNotIn(forbidden, text)

    def test_frozen_fixture_and_built_recipes_are_finite_strict_json(self):
        fixture = json.loads(h3.TEMPLATE.read_text())
        json.dumps(fixture, allow_nan=False)
        self.assertNotIn('1349', fixture)  # NaN is only in the removed upscale cache marker.
        for mode in ('root', 'forward', 'reverse', 'bridge'):
            json.dumps(self.build(mode).graph, allow_nan=False)
            json.dumps(self.build(mode).as_dict(), allow_nan=False)
        for value in (float('nan'), float('inf'), float('-inf')):
            graph = self.build().graph
            graph['1216']['inputs']['crf'] = value
            with self.assertRaises(ValueError): h3.validate_consumed_links(graph)
        with patch.object(Path, 'read_text', return_value=h3.TEMPLATE.read_text().replace('"crf": 19', '"crf": NaN')):
            with self.assertRaises(ValueError): self.build()

    def test_existing_verified_loader_literal_is_preserved_without_stem_inference(self):
        parent = replace(self.parent(), clip='verified-native-output\\actual-returned-name_00007.mp4')
        graph = self.build('forward', parents=(parent,)).graph
        self.assertEqual(graph['2010']['inputs']['clip'], parent.clip)
        self.assertNotIn('mctx', graph['2010']['inputs'])

    def test_schema_checker_requires_real_inventory_and_checks_parent_combo(self):
        # Small synthetic schemas are unit-only; the separately recorded live
        # structural check uses GET /object_info, never a submission.
        graph = self.build('forward').graph
        with self.assertRaisesRegex(ValueError, 'Missing installed node class'):
            h3.validate_graph_contracts(graph, {})
        self.assertEqual(h3._resolved_literal(graph, '1488:1481', 0), 'res_multistep')
        self.assertEqual(h3._resolved_literal(graph, '1488:1481', 1), 20)
        self.assertEqual(h3._resolved_literal(graph, '1334:1330', 0), 'comfy_kitchen')
        # IMAGE pixels are not literal-resolvable model/sampler configuration.
        with self.assertRaisesRegex(ValueError, 'No literal provenance'):
            h3._resolved_literal(graph, '1392', 0)

    def test_every_static_effective_edge_is_protected_not_just_node_presence(self):
        # Mutate every link independently: a disconnected ref/model/control must
        # fail even if every node still exists and the replacement is well-typed.
        original = self.build('bridge').graph
        links = [(node, field) for node, item in original.items()
                 for field, value in item['inputs'].items() if h3._link(value)]
        self.assertGreater(len(links), 50)
        for node, field in links:
            graph = copy.deepcopy(original)
            old = graph[node]['inputs'][field]
            graph[node]['inputs'][field] = ['2004', 0] if old != ['2004', 0] else ['797', 1]
            with self.subTest(node=node, field=field), self.assertRaises(ValueError):
                h3.validate_consumed_links(graph)

    @unittest.skipUnless(importlib.util.find_spec('comfy_sdk'), 'optional installed SDK unavailable')
    def test_sdk_factory_receives_copies_without_mutating_immutable_recipe(self):
        from comfy_sdk.workflows import WorkflowFactory
        for mode in ('root', 'forward', 'reverse', 'bridge'):
            recipe = self.build(mode)
            before = recipe.digest
            workflow = WorkflowFactory().from_json(recipe.graph)
            self.assertEqual(workflow.json, recipe.graph)
            workflow.set_input('2004', 'value', 123)
            self.assertEqual(recipe.digest, before)
            self.assertEqual(recipe.graph['2004']['inputs']['value'], 8801)
            json.dumps(workflow.json, allow_nan=False)
        # Factory acceptance only stores a dict. It is deliberately not claimed
        # as SDK execution, asset retrieval or native family publication proof.


if __name__ == '__main__': unittest.main()
