"""CPU-only compiler tests. Asset IDs/models are fixtures, not render evidence."""
import copy
from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import h3_continuity_graphs as continuity
import h3_root_graphs as root


class RootGraphTests(unittest.TestCase):
    def assets(self, count=3):
        return [{'__type': 'core/ASSET', 'info': {'id': f'unit-reference-{i}'}}
                for i in range(count)]

    def models(self):
        return continuity.H3ContinuityModels(
            unet=continuity.Weight('minimax_h3_ref2va_pruned_int8_convrot.safetensors'),
            clip=continuity.Weight('qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'),
            video_vae=continuity.Weight('minimax_h3_video_vae_fp16.safetensors'),
            audio_vae=continuity.Weight('minimax_h3_audio_vae_fp32.safetensors'))

    def options(self, **changes):
        options = dict(prompt='  A character walks.\nKeep the exact text.  ',
                       operation_id='c' * 32, seed=8801, width=960, height=544,
                       raw_frames=192, models=self.models(), publish_family=True)
        options.update(changes)
        return options

    def build(self, **changes):
        references = changes.pop('references', self.assets())
        return root.build_h3_root(references=references, **self.options(**changes))

    def base(self, references, **changes):
        options = self.options(**changes)
        prompt = options.pop('prompt')
        return continuity.build_h3_continuity('root', references[0], prompt,
                                              parents=(), **options)

    def test_ordered_n1_n2_n3_and_no_compiler_product_cap(self):
        # 12 proves only uncapped structural compilation, not installed capacity.
        for count in (1, 2, 3, 12):
            with self.subTest(count=count):
                references = self.assets(count)
                recipe = self.build(references=references)
                graph = recipe.graph
                self.assertIsInstance(recipe, continuity.ContinuityRecipe)
                self.assertEqual(recipe.as_dict()['references'], references)
                self.assertEqual(recipe.as_dict()['reference'], references[0])
                self.assertEqual(graph['200']['inputs']['image'], references[0])
                self.assertEqual(graph['1383']['inputs']['in_3'], ['200', 0])
                self.assertEqual(graph['797']['inputs']['ref_images.ref_image_0'], ['1392', 0])
                slots = {name: value for name, value in graph['797']['inputs'].items()
                         if name.startswith('ref_images.')}
                self.assertEqual(set(slots), {f'ref_images.ref_image_{i}' for i in range(count)})
                for index in range(1, count):
                    node = f'root_reference_{index}'
                    self.assertEqual(slots[f'ref_images.ref_image_{index}'], [node, 0])
                    self.assertEqual(graph[node], {'class_type': 'LoadImage',
                                                  'inputs': {'image': references[index]}})
                self.assertEqual(sum(n['class_type'] == 'LoadImage' for n in graph.values()), count)
                self.assertFalse(continuity.unconsumed_nodes(graph))
                json.dumps(recipe.as_dict(), allow_nan=False)
        self.assertEqual(self.build(references=tuple(self.assets())).digest, self.build().digest)

    def test_reuses_existing_root_with_explicit_empty_parents(self):
        with patch.object(continuity, 'build_h3_continuity',
                          wraps=continuity.build_h3_continuity) as compiler:
            self.build()
        compiler.assert_called_once_with('root', self.assets()[0],
            self.options()['prompt'], parents=(),
            **{k: v for k, v in self.options().items() if k != 'prompt'})

    def test_exact_base_preserved_except_metadata_and_declared_additions(self):
        for count in (1, 2, 3):
            for publish in (False, True):
                with self.subTest(count=count, publish=publish):
                    references = self.assets(count)
                    base = self.base(references, publish_family=publish)
                    recipe = self.build(references=references, publish_family=publish)
                    graph = recipe.graph
                    for index in range(1, count):
                        graph.pop(f'root_reference_{index}')
                        graph['797']['inputs'].pop(f'ref_images.ref_image_{index}')
                    graph['1216']['inputs']['metadata'] = base.graph['1216']['inputs']['metadata']
                    self.assertEqual(graph, base.graph)
                    continuity.validate_consumed_links(graph)
                    self.assertEqual(recipe.as_dict()['publication'], base.as_dict()['publication'])

    def test_no_parent_loader_pins_or_parent_ancestry(self):
        record = self.build().as_dict()
        self.assertEqual(record['mode'], 'root')
        self.assertEqual(record['parents'], [])
        self.assertEqual(record['anchors'], [])
        graph = record['graph']
        self.assertFalse({'2010', '2011', '2020', '2021'} & graph.keys())
        self.assertFalse({'H3LoadVideoWithMCtx', 'H3MCtxPinSpec'} &
                         {node['class_type'] for node in graph.values()})
        self.assertNotIn('pin_specs', graph['1228']['inputs'])
        # Native saver still consumes ApplyPins' empty pin output, as in root.
        self.assertEqual(graph['1216']['inputs']['pins'], ['1228', 2])

    def test_sampler_guide_weights_saver_and_publication_links(self):
        graph = self.build().graph
        self.assertEqual(graph['1488:1486']['inputs']['latent_image'], ['1228', 1])
        self.assertEqual(graph['1488:1483']['inputs']['conditioning'], ['1228', 0])
        for node in ('1216', '751:632', '751:633'):
            self.assertEqual(graph[node]['inputs']['samples'], ['1488:1486', 1])
        self.assertEqual(graph['1216']['inputs']['conditioning'], ['1228', 0])
        self.assertIs(graph['1216']['inputs']['save_conditioning'], True)
        self.assertEqual(graph['native_family'], {'class_type': 'OpenGenjutsuH3PublishClip',
                                                 'inputs': {'clip': ['1216', 0]}})
        self.assertEqual(graph[continuity.HANDLE_NODE]['inputs']['text'], ['native_family', 0])
        self.assertEqual(json.loads(graph['1290']['inputs']['values'])['steps'], 20)
        for node, field, role in (('725', 'unet_name', 'unet'), ('752:747', 'clip_name', 'clip'),
                                  ('752:748', 'vae_name', 'video_vae'),
                                  ('752:798', 'vae_name', 'audio_vae')):
            self.assertEqual(graph[node]['inputs'][field], getattr(self.models(), role).filename)
        unpublished = self.build(publish_family=False)
        self.assertNotIn('native_family', unpublished.graph)
        self.assertEqual(unpublished.graph[continuity.HANDLE_NODE]['inputs']['text'], ['1216', 0])
        self.assertFalse(unpublished.as_dict()['publication']['family_assets_published'])

    def test_invalid_empty_unordered_and_uncommitted_assets_rejected(self):
        invalid_sets = (None, [], (), {}, 'file.png', {'unit'}, iter(self.assets()))
        invalid_assets = (None, '', 'input.png', [], self.assets(), {},
                          {'type': 'core/ASSET', 'info': {'id': 'unit'}},
                          {'__type': 'core/ASSET'},
                          {'__type': 'core/ASSET', 'info': []})
        invalid_assets += tuple({'__type': 'core/ASSET', 'info': {'id': identifier}}
                                for identifier in (None, '', True, 1, '../bad', 'with space', 'a' * 257))
        for references in invalid_sets:
            with self.subTest(references=references), self.assertRaises(ValueError):
                self.build(references=references)
        for asset in invalid_assets:
            for references in ([asset], self.assets(1) + [asset]):
                with self.subTest(references=references), self.assertRaises(ValueError):
                    self.build(references=references)

    def test_compiler_strict_controls_models_geometry_grid_and_bool_rejection(self):
        invalid = [dict(seed=value) for value in (-1, 2**64, True, 1.0, '1')]
        invalid += [dict(width=value) for value in (True, 31, 961, 16416)]
        invalid += [dict(height=value) for value in (False, 0, 545, 544.0)]
        invalid += [dict(raw_frames=value) for value in (True, 0, 193, 3601, 192.0)]
        invalid += [dict(operation_id=value) for value in (None, '', '../escape', 'C'*32)]
        invalid += [dict(prompt=value) for value in (None, '', ' \n ', True)]
        invalid += [dict(publish_family=value) for value in (None, 0, 1, 'true')]
        invalid += [dict(models=value) for value in (None, {}, self.models().unet)]
        for role in ('unet', 'clip', 'video_vae', 'audio_vae'):
            for value in ('not-a-weight', continuity.Weight('../bad.safetensors'),
                          continuity.Weight('file.safetensors', 'not-a-hash')):
                invalid.append(dict(models=replace(self.models(), **{role: value})))
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.build(**options)

    def test_exact_max_uint64_roundtrips_without_signed_seed_node(self):
        maximum = 2**64 - 1
        recipe = self.build(seed=maximum)
        record = json.loads(recipe.canonical_json)
        self.assertEqual(record['seed'], maximum)
        self.assertEqual(record['graph']['2004']['inputs']['value'], maximum)
        self.assertIn('18446744073709551615', recipe.canonical_json)
        self.assertEqual(record['graph']['1488:1482']['inputs']['noise_seed'], ['2004', 0])
        self.assertNotIn('765', record['graph'])

    def test_saver_metadata_order_immutability_and_digests(self):
        references = self.assets()
        recipe = self.build(references=references)
        original = recipe.as_dict()
        metadata = json.loads(recipe.graph['1216']['inputs']['metadata'])
        self.assertEqual(metadata, {k: v for k, v in original.items()
                                    if k not in ('graph', 'graph_digest', 'publication')})
        self.assertEqual(original['graph_digest'], continuity.canonical_digest(recipe.graph))
        self.assertEqual(recipe.digest, hashlib.sha256(recipe.canonical_json.encode()).hexdigest())
        self.assertEqual(recipe.digest, self.build().digest)
        for changed in (self.build(seed=8802), self.build(references=list(reversed(self.assets()))),
                        self.build(references=self.assets(2)), self.build(publish_family=False)):
            self.assertNotEqual(recipe.digest, changed.digest)
            self.assertNotEqual(original['graph_digest'], changed.as_dict()['graph_digest'])
        references[1]['info']['id'] = 'caller-mutation'
        record = recipe.as_dict()
        record['references'][0]['info']['id'] = 'accessor-mutation'
        graph = recipe.graph
        graph['root_reference_1']['inputs']['image']['info']['id'] = 'graph-mutation'
        self.assertEqual(recipe.as_dict(), original)
        with self.assertRaises(FrozenInstanceError):
            recipe.canonical_json = '{}'

    def test_corrupt_pinned_base_fails_before_expansion(self):
        template = json.loads(continuity.TEMPLATE.read_text())
        template['1488:1486']['inputs']['latent_image'] = ['797', 1]
        with patch.object(Path, 'read_text', return_value=json.dumps(template)), \
                patch.object(root, '_expand_references') as expand:
            with self.assertRaisesRegex(ValueError, 'template.*digest'):
                self.build()
            expand.assert_not_called()
        original_compiler = continuity.build_h3_continuity

        def corrupted_publication(*args, **kwargs):
            record = original_compiler(*args, **kwargs).as_dict()
            record['graph']['native_family']['inputs']['clip'] = ['797', 0]
            return continuity.ContinuityRecipe(continuity._canonical(record))

        with patch.object(continuity, 'build_h3_continuity', side_effect=corrupted_publication), \
                patch.object(root, '_expand_references') as expand:
            with self.assertRaises(ValueError):
                self.build()
            expand.assert_not_called()

    def test_every_effective_edge_including_dynamic_links_rejects_mutation(self):
        references = self.assets()
        recipe = self.build()
        graph = recipe.graph
        base = self.base(references).graph
        metadata = graph['1216']['inputs']['metadata']
        links = [(node, field) for node, item in graph.items()
                 for field, value in item['inputs'].items() if continuity._link(value)]
        self.assertIn(('797', 'ref_images.ref_image_1'), links)
        self.assertIn(('797', 'ref_images.ref_image_2'), links)
        for node, field in links:
            changed = copy.deepcopy(graph)
            changed[node]['inputs'][field] = ['missing', 0]
            with self.subTest(node=node, field=field), self.assertRaises(ValueError):
                root._validate_expansion(changed, base_graph=base, references=references,
                                         metadata=metadata)

    def test_no_unbounded_topology_or_metadata_changes_and_global_validator_unchanged(self):
        references = self.assets()
        recipe = self.build()
        graph = recipe.graph
        base = self.base(references).graph
        metadata = graph['1216']['inputs']['metadata']
        variants = []
        for node in ('root_reference_1', 'root_reference_2'):
            changed = copy.deepcopy(graph)
            changed[node]['inputs']['image'] = self.assets(1)[0]
            variants.append(changed)
        changed = copy.deepcopy(graph)
        changed['797']['inputs']['ref_images.ref_image_3'] = ['200', 0]
        variants.append(changed)
        changed = copy.deepcopy(graph)
        changed['unused'] = {'class_type': 'LoadImage', 'inputs': {'image': references[0]}}
        variants.append(changed)
        for node, field, value in (('1216', 'metadata', '{}'), ('1216', 'save_conditioning', False),
                                    ('2004', 'value', True), ('1290', 'values', 'NaN')):
            changed = copy.deepcopy(graph)
            changed[node]['inputs'][field] = value
            variants.append(changed)
        for index, changed in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                root._validate_expansion(changed, base_graph=base, references=references,
                                         metadata=metadata)
        # Existing strict validator deliberately refuses a dynamic extension.
        with self.assertRaises(ValueError):
            continuity.validate_consumed_links(graph)
        continuity.validate_consumed_links(self.build(references=self.assets(1)).graph)

    @unittest.skipUnless(importlib.util.find_spec('comfy_sdk'), 'optional installed SDK unavailable')
    def test_sdk_factory_construction_only_not_execution(self):
        from comfy_sdk.workflows import WorkflowFactory
        for count in (1, 2, 3):
            recipe = self.build(references=self.assets(count))
            before = recipe.digest
            workflow = WorkflowFactory().from_json(recipe.graph)
            self.assertEqual(workflow.json, recipe.graph)
            workflow.set_input('2004', 'value', 123)
            self.assertEqual(recipe.digest, before)
            self.assertEqual(recipe.graph['2004']['inputs']['value'], 8801)
        # Factory stores graph JSON; this proves neither target schema nor render.


if __name__ == '__main__':
    unittest.main()
