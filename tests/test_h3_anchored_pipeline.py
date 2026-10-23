"""Mode orchestration doubles, not GPU acceptance of Prepend/Bridge."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import continuity_pipeline as pipeline
from h3_av_state import AVState, audio_ticks
from fractions import Fraction
from test_continuity_pipeline import MODELS

A, B = 'a' * 32, 'b' * 32


def family(identity, width=1280):
    context = {'width': width, 'height': 704, 'fps': 24, 'raw_frames': 192,
               'delivered_frames': 192, 'self_id': identity}
    return SimpleNamespace(artifacts=SimpleNamespace(to_manifest=lambda: {'context': context}))


class AnchoredPipelineTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.request = SimpleNamespace(prompt='Prepared effective prompt', raw_frames=192, seed=7)
        self.state = AVState(192, 0, 192, audio_ticks(192), Fraction(0))
        self.families = {A: family('1' * 64), B: family('2' * 64)}
        self.family_patch = patch.object(pipeline, 'get_validated_family', side_effect=lambda work, id: self.families[id])
        self.family_patch.start(); self.addCleanup(self.family_patch.stop)
        self.state_patch = patch.object(pipeline, 'state_from_family', return_value=self.state)
        self.state_patch.start(); self.addCleanup(self.state_patch.stop)

    def submit(self, mode, ids):
        return pipeline.submit_continuation('/work', ids, self.request, mode=mode,
            client=self.client, models=MODELS,
            references=[{'__type': 'core/ASSET', 'info': {'id': 'ref'}}],
            target_fingerprint='f' * 64, work_root='/ops', operation_id='c' * 32,
            inventory=lambda graph: ([], []))

    def test_prepend_and_bridge_use_one_frozen_pipeline_with_ordered_parents(self):
        for mode, ids in (('prepend', (A,)), ('bridge', (A, B))):
            with self.subTest(mode=mode), \
                 patch.object(pipeline, 'restage_parent', side_effect=['a/take.mp4', 'b/take.mp4']) as restage, \
                 patch.object(pipeline, 'create_operation') as create, \
                 patch.object(pipeline, 'collect_forward') as collector, \
                 patch.object(pipeline, 'execute_operation', return_value={'status': 'done'}) as execute:
                result = self.submit(mode, ids)
                self.assertEqual(result['status'], 'done')
                self.assertEqual(restage.call_count, len(ids))
                self.assertEqual(create.call_args.kwargs['parents'], ids)
                self.assertEqual(create.call_args.kwargs['mode'], mode)
                graph = create.call_args.kwargs['graph']
                self.assertEqual(graph['2020']['inputs']['take_from'], 'head' if mode == 'prepend' else 'tail')
                if mode == 'bridge':
                    self.assertEqual(graph['2021']['inputs']['take_from'], 'head')
                    self.assertEqual(graph['2011']['inputs']['clip'], 'b/take.mp4')
                self.assertEqual(collector.call_args.kwargs['operator_label'], 'native-' + mode)
                execute.assert_called_once()

    def test_bad_endpoint_refuses_before_inventory_restage_or_checkpoint(self):
        bad = AVState(158, 35, 123, 263, Fraction(0))
        with patch.object(pipeline, 'state_from_family', return_value=bad), \
             patch.object(pipeline, 'restage_parent') as restage, \
             patch.object(pipeline, 'create_operation') as create:
            with self.assertRaises(ValueError): self.submit('prepend', (A,))
        restage.assert_not_called(); create.assert_not_called()
        self.client.assets.from_file.assert_not_called()
        self.client.submit.assert_not_called()

    def test_geometry_and_native_identity_conflicts_refuse_before_restage(self):
        for source in (family('1' * 64), family('2' * 64, width=704)):
            self.families[B] = source
            with self.subTest(source=source), patch.object(pipeline, 'restage_parent') as restage:
                with self.assertRaises(ValueError): self.submit('bridge', (A, B))
                restage.assert_not_called()
        for mode, ids in (('bridge', (A, A)), ('prepend', (A, B)), ('unknown', (A,))):
            with self.subTest(mode=mode), self.assertRaises(ValueError): self.submit(mode, ids)

    def test_unreadable_saved_timing_is_refused_without_any_upload(self):
        with patch.object(pipeline, 'state_from_family', return_value=None), \
             patch.object(pipeline, 'restage_parent') as restage:
            with self.assertRaisesRegex(ValueError, 'timing'):
                self.submit('prepend', (A,))
            restage.assert_not_called()

    def test_actual_child_state_is_checked_before_registration_and_output_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'output'
            def download(*args):
                destination = args[2]
                destination.mkdir()
                (destination / 'take.mctx.safetensors').write_bytes(b'header test double')
            for matches in (False, True):
                destination = folder if not matches else Path(directory) / 'matching'
                writer = download
                actual = self.state if matches else AVState(192, 35, 157, 320, Fraction(0))
                with patch.object(pipeline, 'download_h3_artifacts', side_effect=writer), \
                     patch.object(pipeline, 'read_safetensors_header'), \
                     patch.object(pipeline, 'state_from_header', return_value=actual), \
                     patch.object(pipeline, 'import_family', return_value=SimpleNamespace(take_id=A)) as publish:
                    collect = pipeline.collect_forward('/work', destination, compiled_graph={},
                        expected_state=self.state, operator_label='native-prepend')
                    if matches:
                        self.assertEqual(collect(SimpleNamespace(id='remote'), None, A), A)
                        self.assertEqual(publish.call_args.kwargs['operator_label'], 'native-prepend')
                    else:
                        with self.assertRaisesRegex(ValueError, 'not registered'):
                            collect(SimpleNamespace(id='remote'), None, A)
                        publish.assert_not_called()
                    self.assertTrue((destination / 'take.mctx.safetensors').exists())

    def test_preflight_checks_both_parent_and_prompt_graphs_before_client_work(self):
        seen = []
        def inventory(graph):
            seen.append(graph)
            return (['missing-node'], []) if '2021' in graph else ([], [])
        with self.assertRaises(pipeline.TargetMissingDependencies):
            pipeline.preflight_continuation('/work', A, mode='bridge', second_take_id=B,
                models=MODELS, direction='Create a connection', reference_count=1,
                raw_frames=192, inventory=inventory)
        self.assertEqual(len(seen), 2)
        self.assertIn('2021', seen[0])
        self.client.assets.from_file.assert_not_called()
