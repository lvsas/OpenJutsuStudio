"""Synthetic text/SDK mocks: reference closure, never perceptual/GPU acceptance."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_forward_api as api
from continuity_requests import ForwardRequest
import h3_prompt_generator as gen

REF = {'__type': 'core/ASSET', 'info': {'id': 'synthetic-character'}}
SCENE = {'__type': 'core/ASSET', 'info': {'id': 'synthetic-source-scene'}}


class ContinuationReferenceContractTests(unittest.TestCase):
    def test_observed_unbound_scene_picture_is_rejected_without_rewriting(self):
        # Same role defect as the observed run; no private creator prompt copied.
        text = 'summary:\nThe saved scene from <Picture 2> continues with <Picture 1>.'
        with self.assertRaisesRegex(ValueError, 'not supplied'):
            gen.validate_continuation_prompt_references(text, 1)

    def test_valid_text_is_returned_byte_identical(self):
        text = '  summary:\nÉclairage conservé. <Picture 1> and <Picture 2>; <Audio 1>.\n'
        self.assertEqual(gen.validate_continuation_prompt_references(
            text, 2, preserve_source_audio=True).encode(), text.encode())
        source_only = 'The existing performers and setting continue; no new references.'
        self.assertEqual(gen.validate_continuation_prompt_references(source_only, 0), source_only)

    def test_malformed_media_angle_tags_are_rejected(self):
        for tag in ('<Picture2>', '<Audio 1, 2>', '<Video 1-2>',
                    '<Picture>', '<Audio 1.5>', '<Video -1>', '<Picture 1x>',
                    '<picture 1', '<Audio 1, 2'):
            with self.subTest(tag=tag):
                with self.assertRaisesRegex(ValueError, 'malformed'):
                    gen.validate_continuation_prompt_references(
                        f'Before {tag} after', 2, preserve_source_audio=True)

    def test_ambiguous_numbered_media_syntax_is_rejected_generically(self):
        for role in ('Picture', 'Audio', 'Video'):
            for suffix in (' #2>', ': 2>', ' ２>', ' ٢>', ' ²>',
                           ' [2]>', ' / 2>', ' #2', ': ２', ' २'):
                tag = f'<{role}{suffix}'
                with self.subTest(tag=tag):
                    with self.assertRaisesRegex(ValueError, 'malformed'):
                        gen.validate_continuation_prompt_references(
                            f'Before {tag} after', 2, preserve_source_audio=True)

    def test_non_media_prose_and_valid_tags_remain_byte_identical(self):
        for text in ('  Éclairage < picture\t2 >; <Audio 1>.\n',
                     'Audio 1, Picture2 and Video 1-2 are ordinary prose.',
                     'Use <Picture frame> and <Audio description> as prose.',
                     'Keep <Picture frame 2>, <Audio description 1>, <Video-game 3>.',
                     'The <Picturebook> and <Video-game> are unrelated.',
                     'x < 2 and y > 1; <Subject 1> stays.'):
            with self.subTest(text=text):
                self.assertEqual(gen.validate_continuation_prompt_references(
                    text, 2, preserve_source_audio=True).encode(), text.encode())

    def test_zero_missing_out_of_range_audio_and_video_references_are_closed(self):
        for text, count, audio in (
            ('<Picture 0>', 1, False), ('<Picture 1>', 0, False),
            ('<Picture 3>', 2, False), ('< picture\t2 >', 1, False),
            ('<Audio 1>', 1, False), ('<Audio 2>', 1, True),
            ('<Video 1>', 1, True),
        ):
            with self.subTest(text=text, count=count, audio=audio):
                with self.assertRaisesRegex(ValueError, 'not supplied'):
                    gen.validate_continuation_prompt_references(
                        text, count, preserve_source_audio=audio)

    def test_context_has_no_h3_numbered_alias_and_sheet_is_not_a_clone_request(self):
        graph = gen.build_prompt_graph('Keep the scene and add the requested person.',
                                      [REF], continuation_frame=SCENE)
        slot = graph[gen.DIRECTION_NODE]['inputs']['string']
        self.assertIn('<Picture 1>', slot)
        self.assertNotIn('<Picture 2>', slot)
        self.assertIn('last attached image', slot)
        self.assertIn('multiple views of the same individual', slot)
        self.assertIn('Describe the visible existing performers', slot)
        self.assertEqual(graph['5833_26']['inputs']['string'], gen.policy_text())
        self.assertEqual(graph[gen.BATCH_NODE]['inputs']['inputcount'], 2)

    def client(self):
        client = Mock()
        client.workflows.from_json.side_effect = lambda value: value
        client.run.return_value = SimpleNamespace(status='succeeded')
        client.assets.from_file.return_value.as_reference.return_value = REF
        return client

    def test_continuation_readback_refuses_unknown_role_without_retry(self):
        client = self.client()
        with patch.object(api, 'read_prompt_text', return_value='Scene from <Picture 2>'):
            with self.assertRaisesRegex(ValueError, 'not supplied'):
                api.refine_prompt(client, 'Continue.', [REF], continuation_frame=SCENE)
        client.run.assert_called_once()

    def test_valid_readback_and_root_behavior_are_unchanged(self):
        for scene, text in ((SCENE, '  <Picture 1> joins the existing performers.\n'),
                            (None, 'Root generator text is outside this continuation-only check. <Picture 2>')):
            with self.subTest(scene=scene):
                client = self.client()
                with patch.object(api, 'read_prompt_text', return_value=text):
                    self.assertEqual(api.refine_prompt(client, 'Create.', [REF],
                                                       continuation_frame=scene), text)
                client.run.assert_called_once()

    def test_production_hunt_uses_the_same_reference_closure(self):
        import app
        client = self.client()
        with patch.object(app, 'make_client', return_value=client), \
             patch.object(app, '_continuity_models', return_value='synthetic-models'), \
             patch.object(app, 'preflight_continuation', return_value=None), \
             patch.object(api, 'get_validated_family', return_value=SimpleNamespace()), \
             patch.object(api, '_extract_continuation_frame', return_value=Path('synthetic-frame.png')), \
             patch.object(api, 'read_prompt_text', return_value='Scene from <Picture 2>'), \
             patch.object(app, 'submit_forward') as submit:
            with self.assertRaisesRegex(ValueError, 'not supplied'):
                app._hunt_refine('Continue.', 'a' * 32,
                                 reference_paths=(Path('synthetic.png'),), audio_context=None)
        client.run.assert_called_once()
        submit.assert_not_called()

    def test_production_forward_does_not_submit_video_after_bad_prompt(self):
        client = self.client()
        with patch.object(api, 'parent_references', return_value=[Path('synthetic.png')]), \
             patch.object(api, 'get_validated_family', return_value=SimpleNamespace()), \
             patch.object(api, '_extract_continuation_frame', return_value=Path('synthetic-frame.png')), \
             patch.object(api, 'read_prompt_text', return_value='The saved scene is <Picture 2>.'), \
             patch.object(api, 'precheck_source_audio'), \
             patch.object(api, 'submit_forward') as submit:
            runner = api.make_forward_runner(client_factory=lambda: client,
                models_factory=lambda: 'synthetic-models', fingerprint='synthetic-target',
                work_root='synthetic-operations', preflight=lambda *a, **k: None)
            with self.assertRaisesRegex(ValueError, 'not supplied'):
                runner('synthetic-work', 'a' * 32, ForwardRequest(
                    request_id='b' * 32, prompt='Continue the scene.', seed=7, raw_frames=158))
        submit.assert_not_called()
        client.run.assert_called_once()  # One refiner only; no sample or automatic retry.


class ContinuationAuthorityTests(unittest.TestCase):
    def test_system_instruction_is_generic_and_continuation_only(self):
        graph = gen.build_prompt_graph('Continue in one uninterrupted shot.', [REF],
                                      continuation_frame=SCENE)
        system = graph[gen.GENERATE_NODE]['inputs']['system_prompt']
        self.assertEqual(system, gen.CONTINUATION_SYSTEM_PROMPT)
        self.assertIn('single continuous shot', system)
        self.assertIn('explicitly requests multiple shots', system)
        self.assertIn('phases within that shot', system)
        for fixture_term in ('orange', 'rapper', 'ninja', '00:03.000'):
            self.assertNotIn(fixture_term, system)
        root = gen.build_prompt_graph('Create a scene.', [REF])
        self.assertNotIn('system_prompt', root[gen.GENERATE_NODE]['inputs'])
        self.assertEqual(graph['5833_26']['inputs']['string'], gen.policy_text())
        self.assertEqual(graph[gen.CLIP_NODE], root[gen.CLIP_NODE])

    def test_single_and_multishot_directions_reach_the_same_policy_unmodified(self):
        for direction in ('Un plan continu sans coupe, avec un travelling arrière.',
                          'Deux plans avec une coupe à 00:03.000, sans changer les personnages.'):
            with self.subTest(direction=direction):
                graph = gen.build_prompt_graph(direction, [REF], continuation_frame=SCENE)
                self.assertIn(direction, graph[gen.DIRECTION_NODE]['inputs']['string'])
                self.assertIn('system_prompt', graph[gen.GENERATE_NODE]['inputs'])

    def test_inventory_refuses_missing_or_wrong_type_system_capability(self):
        import readiness
        graph = {'text': {'class_type': 'TextGenerate',
                          'inputs': {'prompt': 'synthetic', 'system_prompt': 'synthetic rule'}}}
        for spec in (None, ['INT', {}], [], 'STRING'):
            with self.subTest(spec=spec):
                fields = {} if spec is None else {'system_prompt': spec}
                with self.assertRaisesRegex(ValueError, 'system instructions'):
                    readiness._inventory({'TextGenerate': {'input': {'optional': fields}}}, graph)
        info = {'TextGenerate': {'input': {'optional': {'system_prompt': ['STRING', {}]}}}}
        self.assertEqual(readiness._inventory(info, graph), ([], []))
        root = {'text': {'class_type': 'TextGenerate', 'inputs': {'prompt': 'synthetic'}}}
        self.assertEqual(readiness._inventory({'TextGenerate': {'input': {}}}, root), ([], []))

    def test_preflight_inventories_actual_context_and_system_instruction(self):
        import continuity_pipeline as pipeline
        from tests import test_continuity_pipeline as fixtures
        inventory = Mock(return_value=([], []))
        with patch.object(pipeline, '_checked_anchors', return_value=(
                (SimpleNamespace(),), ({'width': 1280, 'height': 704},), None)), \
             patch.object(pipeline, 'source_audio_context', return_value=None):
            pipeline.preflight_continuation('synthetic', 'a' * 32, models=fixtures.MODELS,
                direction='Keep one shot.', reference_count=1, inventory=inventory)
        prompt = inventory.call_args_list[1].args[0]
        self.assertIn('system_prompt', prompt[gen.GENERATE_NODE]['inputs'])
        batch = prompt[gen.BATCH_NODE]['inputs']
        self.assertNotEqual(batch['image_1'], batch['image_2'])

    def test_old_prompt_target_refuses_before_production_client_or_refinement(self):
        from functools import partial
        import continuity_pipeline as pipeline
        import readiness
        from tests import test_continuity_pipeline as fixtures

        def inventory(graph):
            for key, node in graph.items():
                if node['class_type'] == 'TextGenerate':
                    return readiness._inventory({'TextGenerate': {'input': {}}}, {key: node})
            return [], []

        client = Mock()
        with patch.object(pipeline, '_checked_anchors', return_value=(
                (SimpleNamespace(),), ({'width': 1280, 'height': 704},), None)), \
             patch.object(pipeline, 'source_audio_context', return_value=None), \
             patch.object(api, 'parent_references', return_value=[Path('synthetic.png')]), \
             patch.object(api, 'refine_continuation_prompt') as refine, \
             patch.object(api, 'submit_forward') as submit:
            runner = api.make_forward_runner(client_factory=client,
                models_factory=lambda: fixtures.MODELS, fingerprint='synthetic-target',
                work_root='synthetic-operations',
                preflight=partial(pipeline.preflight_continuation, inventory=inventory))
            with self.assertRaisesRegex(ValueError, 'system instructions'):
                runner('synthetic', 'a' * 32, ForwardRequest(
                    request_id='b' * 32, prompt='Continue.', seed=7, raw_frames=158))
        client.assert_not_called()
        refine.assert_not_called()
        submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
