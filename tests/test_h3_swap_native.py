"""Native Swap graph contracts, not GPU/tensor/weight verification.

Hashes and SDK IDs below are deliberately synthetic unit-test attestations.
"""
import copy
from dataclasses import asdict
import unittest

from h3_graphs import H3Models, REFERENCE_NODE
from h3_recipe import make_recipe, bind_frames
from h3_continuity_graphs import Weight
from h3_swap_native import build_swap_native_capture, SAVE_NODE, HANDLE_NODE, AUDIO_NODE


class NativeSwapTests(unittest.TestCase):
    operation = 'a' * 32

    def inputs(self, count=56, source_audio=True, references=1):
        recipe = bind_frames(make_recipe(source_width=960, source_height=544,
                            reference_descriptions=['Person'] * references), count,
                             source_audio=source_audio)
        graph = copy.deepcopy(recipe['graph_template'])
        def asset(identifier):
            return {'__type': 'core/ASSET', 'info': {'id': identifier}}
        graph['155']['inputs']['video'] = asset('source-id')
        for index in range(references):
            graph[str(REFERENCE_NODE + index)]['inputs']['image'] = asset(f'person-{index}')
        graph['156']['inputs']['filename_prefix'] = f'OpenGenjutsu/h3-{self.operation}'
        weights = {role: Weight(name, '1' * 64) for role, name in asdict(H3Models()).items()}
        return recipe, graph, weights

    def capture(self, count=56, source_audio=True, references=1):
        recipe, graph, weights = self.inputs(count, source_audio, references)
        return build_swap_native_capture(recipe, graph, operation_id=self.operation, weights=weights)

    def test_preserves_every_existing_node_and_captures_final_hr_state(self):
        recipe, graph, weights = self.inputs()
        before = copy.deepcopy((recipe, graph, weights))
        captured = build_swap_native_capture(recipe, graph, operation_id=self.operation, weights=weights)
        out = captured.graph
        for key in graph:
            self.assertEqual(out[key], graph[key])
        self.assertEqual((recipe, graph, weights), before)
        save = out[SAVE_NODE]['inputs']
        self.assertEqual(save['samples'], ['170', 1])
        self.assertEqual(save['images'], ['122', 0])
        self.assertEqual(save['conditioning'], ['136', 0])
        self.assertTrue(save['save_conditioning'])
        self.assertNotIn('pins', save)  # A root, not a fabricated ancestor.
        self.assertEqual(out[HANDLE_NODE]['inputs']['text'], [SAVE_NODE, 0])

    def test_native_audio_is_decoded_from_same_av_not_borrowed_from_source(self):
        for source_audio in (True, False):
            with self.subTest(source_audio=source_audio):
                result = self.capture(source_audio=source_audio)
                graph, record = result.graph, result.as_dict()
                self.assertEqual(graph['native_swap_av']['inputs']['av_latent'], ['170', 1])
                self.assertEqual(graph[AUDIO_NODE]['inputs'],
                                 {'samples': ['native_swap_av', 1], 'vae': ['120', 0]})
                self.assertEqual(graph[SAVE_NODE]['inputs']['audio'], [AUDIO_NODE, 0])
                self.assertEqual(record['audio']['native'], 'decoded-final-sampler-av')
                self.assertEqual(record['audio']['display'],
                                 'preserved-source' if source_audio else 'silent')

    def test_hr_geometry_and_padding_are_not_presented_as_trimmed_swap_identity(self):
        for count in (56, 96):
            recipe, _, _ = self.inputs(count)
            record = self.capture(count).as_dict()
            self.assertEqual(record['geometry']['width'], recipe['output_width'])
            self.assertEqual(record['geometry']['height'], recipe['output_height'])
            self.assertEqual(record['geometry']['raw_frames'], recipe['inference_frames'])
            self.assertEqual(record['geometry']['display_frames'], count)
            self.assertEqual(record['geometry']['padding_frames'], recipe['inference_frames'] - count)
            self.assertFalse(record['runtime_verified'])
            self.assertFalse(record['forward_verified'])
            self.assertEqual(record['endpoint'], 'raw-equals-visible' if count == 56
                             else 'padded-endpoint-needs-window-policy')

    def test_all_effective_weights_and_lora_strengths_are_recorded(self):
        record = self.capture().as_dict()
        self.assertEqual(set(record['weights']), set(asdict(H3Models())))
        self.assertEqual(record['loras'], [
            {'role': 'turbo_lora', 'strength_model': 0.9},
            {'role': 'swap_lora', 'strength_model': 1.0}])
        self.assertEqual(record['sampler_output'], ['170', 1])

    def test_rejects_missing_or_substituted_weight_attestations(self):
        recipe, graph, weights = self.inputs()
        invalid = [dict(weights, swap_lora=Weight('different.safetensors', '1' * 64)),
                   {k: v for k, v in weights.items() if k != 'swap_lora'},
                   dict(weights, unet=Weight(weights['unet'].filename, 'unknown'))]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_swap_native_capture(recipe, graph, operation_id=self.operation, weights=value)

    def test_rejects_sampler_decode_conditioning_geometry_and_lora_drift(self):
        recipe, graph, weights = self.inputs()
        mutations = [('122', 'samples', ['125', 1]), ('176', 'conditioning', ['136', 1]),
                     ('159', 'strength_model', 0.0), ('169', 'mode.width', 32),
                     ('170', 'latent_image', ['136', 1]), ('129', 'noise_seed', 5),
                     ('136', 'length', True)]
        for node, field, value in mutations:
            for tamper_template in (False, True):
                r, g = copy.deepcopy(recipe), copy.deepcopy(graph)
                g[node]['inputs'][field] = value
                if tamper_template:
                    r['graph_template'][node]['inputs'][field] = value
                with self.subTest(node=node, template=tamper_template), self.assertRaises(ValueError):
                    build_swap_native_capture(r, g, operation_id=self.operation, weights=weights)

    def test_requires_bound_recipe_committed_assets_and_server_prefix(self):
        recipe, graph, weights = self.inputs()
        for node, field, value in [('155', 'video', '/private/source.mp4'),
                                   ('137', 'image', {'__type': 'core/ASSET', 'info': {}}),
                                   ('156', 'filename_prefix', '../other')]:
            g = copy.deepcopy(graph); g[node]['inputs'][field] = value
            with self.subTest(node=node), self.assertRaises(ValueError):
                build_swap_native_capture(recipe, g, operation_id=self.operation, weights=weights)
        with self.assertRaises(ValueError):
            build_swap_native_capture(make_recipe(source_width=960, source_height=544), graph,
                                      operation_id=self.operation, weights=weights)
        for identifier in ('../escape', 'A' * 32, '', None):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                build_swap_native_capture(recipe, graph, operation_id=identifier, weights=weights)

    def test_optional_sdk_publication_consumes_saved_clip_and_returns_relative_handle(self):
        recipe, graph, weights = self.inputs()
        capture = build_swap_native_capture(recipe, graph, operation_id=self.operation,
                                            weights=weights, publish_family=True)
        out = capture.graph
        self.assertEqual(out['native_swap_family'], {
            'class_type': 'OpenGenjutsuH3PublishClip', 'inputs': {'clip': [SAVE_NODE, 0]}})
        self.assertEqual(out[HANDLE_NODE]['inputs']['text'], ['native_swap_family', 0])
        self.assertEqual(capture.as_dict()['family_node'], 'native_swap_family')
        for value in ('yes', 1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_swap_native_capture(recipe, graph, operation_id=self.operation,
                                          weights=weights, publish_family=value)

    def test_sdk_factory_accepts_capture_without_mutating_its_snapshot(self):
        from comfy_sdk.workflows import WorkflowFactory
        capture = self.capture()
        workflow = WorkflowFactory().from_json(capture.graph)
        self.assertEqual(workflow.json, capture.graph)
        workflow.set_input(SAVE_NODE, 'save_conditioning', False)
        self.assertTrue(capture.graph[SAVE_NODE]['inputs']['save_conditioning'])

    def test_reference_order_immutable_copies_and_content_digest(self):
        capture = self.capture(references=2)
        self.assertEqual(capture.as_dict()['references'], ['person-0', 'person-1'])
        changed = capture.graph; changed[SAVE_NODE]['inputs']['save_conditioning'] = False
        self.assertTrue(capture.graph[SAVE_NODE]['inputs']['save_conditioning'])
        self.assertEqual(capture.digest, self.capture(references=2).digest)
        recipe, graph, weights = self.inputs(references=2)
        graph['137']['inputs']['image']['info']['id'] = 'another-person'
        self.assertNotEqual(capture.digest, build_swap_native_capture(
            recipe, graph, operation_id=self.operation, weights=weights).digest)


if __name__ == '__main__':
    unittest.main()
