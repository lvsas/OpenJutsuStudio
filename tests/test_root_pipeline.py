"""CPU-only root compiler/service/collector proofs with mocked SDK transport.

Synthetic tensor envelopes + mocked MP4 probing are NOT H3 render evidence.
The existing operation checkpoints, compiler and family importer execute for real.
"""
import copy
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuable_take as ct
import continuity_attempts as attempts
import continuity_pipeline as common
import continuity_root_pipeline as root
from continuity_root_api import _store_reference
from continuity_forward_api import parent_references
from continuity_requests import PreparedH3Request
from h3_av_state import AVState, tail_fits, state_from_family
from h3_continuity_graphs import H3ContinuityModels, Weight, validate_consumed_links
from readiness import _inventory
from tests.test_root_attempts import image_bytes
from tests.test_timeline_artifact_contract import tensor_file

MODELS = H3ContinuityModels(
    unet=Weight('minimax_h3_ref2va_pruned_int8_convrot.safetensors'),
    clip=Weight('qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'),
    video_vae=Weight('minimax_h3_video_vae_fp16.safetensors'),
    audio_vae=Weight('minimax_h3_audio_vae_fp32.safetensors'))
FINGERPRINT = 'f' * 64


class RootPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name) / 'work'
        self.operations = Path(self.tmp.name) / 'operations'
        self.context = {'reference_ids': [_store_reference(self.work, image_bytes(color))
                                        for color in ('red', 'green', 'blue')],
                        'width': 32, 'height': 32}
        self.paths = root.resolve_root_references(self.work, self.context)
        self.references = [{'__type': 'core/ASSET', 'info': {'id': f'committed-{index}'}}
                           for index in range(3)]
        self.request = PreparedH3Request(request_id='a' * 32, prompt='Private prepared text ' * 220,
                                         seed=2 ** 64 - 1, raw_frames=192)
        self.client = MagicMock()
        self.remote = MagicMock(id='unit-root-job', status='succeeded')
        self.client.submit.return_value = self.remote
        self.client.jobs.get.return_value = self.remote

    def submit(self, **changes):
        options = dict(client=self.client, models=MODELS, references=self.references,
                       reference_paths=self.paths, root_context=self.context,
                       target_fingerprint=FINGERPRINT, work_root=self.operations,
                       operation_id='b' * 32)
        options.update(changes)
        return root.submit_root(self.work, self.request, **options)

    def download(self, remote, node, folder, *, wrong_state=False):
        """Explicit synthetic family; CPU import is real, video probe is mocked."""
        self.assertEqual(node, 'native_family')
        folder.mkdir(parents=True)
        payload = b'EXPLICIT SYNTHETIC VIDEO FIXTURE; NOT A RENDER'
        (folder / 'take.mp4').write_bytes(payload)
        identity = hashlib.sha256(payload).hexdigest()
        state = root.root_state(self.request.raw_frames)
        meta = {'format': 'mctx_v1', 'self_id': identity,
                'width': '32', 'height': '32', 'fps': '24',
                'raw_frames': str(state.raw_frames), 'delivered_frames': str(state.delivered_frames),
                'pinned_head_frames': '0', 'pinned_tail_frames': '0', 'audio_phase': '0',
                'pins': '[]', 'parent_id': '', 'relation': ''}
        (folder / 'take.mctx.safetensors').write_bytes(tensor_file({
            'video': ('F16', [1, 24, ((state.raw_frames - 5) // 17) * 5 + 2, 2, 2], None),
            'audio': ('F16', [1, 32, 2, state.audio_ticks - int(wrong_state)], None)}, meta))
        structure = json.dumps({'__list__': [{'__list__': [
            {'__tensor__': 'embedding'}, {'__dict__': {}}]}]}).encode()
        (folder / 'take.cond.safetensors').write_bytes(tensor_file({
            'embedding': ('F32', [1, 2, 3], None),
            'structure': ('U8', [len(structure)], structure)},
            {'format': 'obvpm_cond_v1', 'self_id': identity}))

    def probe(self):
        return patch('timeline_artifacts.probe_mp4', return_value={
            'width': 32, 'height': 32, 'fps': 24., 'frames': self.request.raw_frames})

    def test_state_matches_native_producer_rounding_no_pins_and_continuable_tail(self):
        expected = [(56, 93), (73, 122), (124, 207), (158, 263), (192, 320), (277, 462)]
        for frames, ticks in expected:
            with self.subTest(frames=frames):
                self.assertEqual(root.root_state(frames), AVState(frames, 0, frames, ticks, Fraction(0)))
                self.assertTrue(tail_fits(root.root_state(frames)))
        for value in (True, 192., '192', 0, 5, 22, 193, 3609):
            with self.subTest(value=value), self.assertRaises(ValueError):
                root.root_state(value)
        for raw in range(39, 3601, 17):
            self.assertTrue(tail_fits(root.root_state(raw)))

    def test_resolver_uses_only_ids_preserves_order_and_never_creates_missing_files(self):
        reversed_context = self.context | {'reference_ids': list(reversed(self.context['reference_ids']))}
        self.assertEqual(root.resolve_root_references(self.work, reversed_context), tuple(reversed(self.paths)))
        before = set(self.work.rglob('*'))
        for context in (self.context | {'reference_ids': ['f' * 32]},
                        self.context | {'reference_ids': ['../../outside']},
                        self.context | {'reference_ids': []}, self.context | {'path': str(self.paths[0])}):
            with self.subTest(context=context), self.assertRaises(ValueError):
                root.resolve_root_references(self.work, context)
        self.assertEqual(before, set(self.work.rglob('*')))

    def test_symlink_reference_or_ancestor_and_nonregular_files_are_refused_before_cost(self):
        original = self.paths[0].read_bytes()
        outside = Path(self.tmp.name) / 'external.png'
        outside.write_bytes(original)
        self.paths[0].unlink()
        self.paths[0].symlink_to(outside)
        with self.assertRaises(ValueError):
            self.submit()
        self.client.submit.assert_not_called()
        self.paths[0].unlink()
        self.paths[0].mkdir()
        with self.assertRaises(ValueError):
            root.resolve_root_references(self.work, self.context)
        linked_work = Path(self.tmp.name) / 'linked-work'
        linked_work.symlink_to(self.work, target_is_directory=True)
        with self.assertRaises(ValueError):
            root.resolve_root_references(linked_work, self.context)
        self.assertFalse(self.operations.exists())

    def test_invalid_controls_refs_order_and_paths_are_refused_before_operation_or_sdk(self):
        variants = [{'reference_paths': self.paths[::-1]},
                    {'reference_paths': [Path('/private/other.png')] * 3},
                    {'references': self.references[:1]},
                    {'references': self.references[:2] + ['not-an-asset']},
                    {'root_context': self.context | {'width': True}},
                    {'root_context': self.context | {'reference_ids': ['f' * 32]}},
                    {'operation_id': '../operation'}]
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.submit(**changes)
        self.assertFalse(self.operations.exists())
        self.client.submit.assert_not_called()
        self.client.run.assert_not_called()
        self.client.assets.from_file.assert_not_called()

    def test_preflight_checks_final_expanded_root_and_authored_prompt_without_sdk(self):
        probe = Mock(side_effect=[([], []), ([], ['missing-prompt-model.safetensors'])])
        with self.assertRaises(root.TargetMissingDependencies):
            root.preflight_root(models=MODELS, direction='Continue walking', root_context=self.context,
                                raw_frames=192, inventory=probe)
        self.assertEqual(probe.call_count, 2)
        generation, prompt = [call.args[0] for call in probe.call_args_list]
        self.assertIn('native_family', generation)
        self.assertIn('prompt_text', prompt)
        for graph in (generation, prompt):
            self.assertEqual(sum(n['class_type'] == 'LoadImage' for n in graph.values()), 3)
        self.assertNotIn('pin_specs', generation['1228']['inputs'])
        self.assertEqual(generation['797']['inputs']['ref_images.ref_image_2'], ['root_reference_2', 0])
        self.client.submit.assert_not_called()
        self.assertFalse(self.operations.exists())

    def test_root_inventory_final_graph_works_without_weakening_global_topology_guard(self):
        seen = []
        def inventory(graph):
            seen.append(graph)
            # Exercise real missing_dependencies with its read-only target GET
            # replaced by fixture object_info; no target is contacted.
            info = {}
            for node in graph.values():
                kind = node['class_type']
                fields = info.setdefault(kind, {'input': {'required': {}}})['input']['required']
                for key, value in node['inputs'].items():
                    if key in {'unet_name', 'clip_name', 'vae_name', 'lora_name', 'model_name'} and isinstance(value, str):
                        fields.setdefault(key, [[]])[0].append(value)
            with patch('readiness._target_object_info', return_value=info):
                return root.missing_dependencies(graph)
        root.preflight_root(models=MODELS, direction='Use all three pictures', root_context=self.context,
                            raw_frames=192, inventory=inventory)
        with self.assertRaises(ValueError):
            validate_consumed_links(seen[0])
        self.assertEqual(len(seen), 2)

    def test_preflight_bad_context_length_or_profile_never_calls_inventory(self):
        inventory = Mock()
        for changes in ({'root_context': self.context | {'reference_ids': []}},
                        {'root_context': self.context | {'height': 33}},
                        {'raw_frames': 22}, {'models': None}, {'direction': ''}):
            options = dict(models=MODELS, direction='Keep walking', root_context=self.context,
                           raw_frames=192, inventory=inventory)
            options.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                root.preflight_root(**options)
        inventory.assert_not_called()

    def test_real_sdk_checkpoint_and_collector_parentless_no_restage_carries_all_refs(self):
        with self.probe(), patch.object(common, 'download_h3_artifacts', side_effect=self.download), \
                patch.object(common, 'restage_parent', side_effect=AssertionError('root cannot restage')):
            result = self.submit()
        self.assertEqual(result['status'], 'done')
        self.assertEqual((result['mode'], result['take_id']), ('root', 'b' * 32))
        self.client.submit.assert_called_once()
        self.client.run.assert_not_called()
        self.client.assets.from_file.assert_not_called()
        operation = json.loads((self.operations / 'timeline/continuity-operations' / ('b' * 32) / 'operation.json').read_text())
        self.assertEqual(operation['intent']['mode'], 'root')
        self.assertEqual(operation['intent']['parents'], [])
        graph = operation['intent']['graph']
        self.assertFalse({'2010', '2011', '2020', '2021'} & graph.keys())
        self.assertEqual(graph['200']['inputs']['image'], self.references[0])
        self.assertEqual(graph['root_reference_2']['inputs']['image'], self.references[2])
        self.assertEqual(graph['761:763']['inputs']['value'], self.request.prompt)
        self.assertEqual(self.client.submit.call_args.kwargs['idempotency_key'], 'opengenjutsu-native-' + 'b' * 32)
        with self.probe():
            family = ct.get_validated_family(self.work, 'b' * 32)
            self.assertEqual(state_from_family(family), root.root_state(192))
            carried = parent_references(self.work, 'b' * 32)
        self.assertEqual([p.read_bytes() for p in carried], [p.read_bytes() for p in self.paths])
        # Re-entering the same operation uses its checkpoint, no new submit.
        with self.probe():
            self.assertEqual(self.submit(), result)
        self.assertEqual(self.client.submit.call_count, 1)

    def test_collection_measured_state_drift_fails_closed_and_keeps_download(self):
        def download(*args):
            self.download(*args, wrong_state=True)
        with self.probe(), patch.object(common, 'download_h3_artifacts', side_effect=download):
            with self.assertRaisesRegex(ValueError, 'timing differs'):
                self.submit()
        folder = self.work / 'media' / ('root-' + 'b' * 32)
        self.assertTrue((folder / 'take.mctx.safetensors').is_file())
        self.assertFalse((self.work / 'timeline/continuable-takes' / ('b' * 32)).exists())
        from continuity_jobs import get_operation
        self.assertEqual(get_operation(self.operations, 'b' * 32)['status'], 'collecting')

    def test_real_shared_worker_callbacks_use_root_pipeline_and_refine_only_once(self):
        record = attempts.create(self.operations, take_id=None, mode='root', root_context=self.context,
            request_id='e' * 32, prompt='Direction for all three pictures', raw_frames=192, seeds=[0, 2 ** 64 - 1])
        refiner = Mock(return_value=self.request.prompt)
        def refine(prompt, parent, *, mode, root_context):
            self.assertIsNone(parent)
            self.assertEqual(mode, 'root')
            root.preflight_root(models=MODELS, direction=prompt, root_context=root_context,
                                raw_frames=192, inventory=lambda graph: ([], []))
            return refiner(prompt, root_context)
        def submit(opid, prompt, seed, raw, parent, *, mode, root_context):
            self.assertIsNone(parent)
            self.assertEqual(mode, 'root')
            request = PreparedH3Request(request_id='e' * 32, prompt=prompt, seed=seed, raw_frames=raw)
            result = root.submit_root(self.work, request, client=self.client, models=MODELS,
                references=self.references, reference_paths=self.paths, root_context=root_context,
                target_fingerprint=FINGERPRINT, work_root=self.operations, operation_id=opid)
            return result['take_id']
        worker = attempts.Worker(self.operations, refine=refine, submit=submit)
        with self.probe(), patch.object(common, 'download_h3_artifacts', side_effect=self.download):
            worker.start(record['attempt_id'])
            thread = worker._thread
            thread.join(10)
        self.assertFalse(thread.is_alive())
        result = attempts.load(self.operations, record['attempt_id'])
        self.assertEqual(result['status'], 'done', result)
        self.assertEqual([c['take_id'] for c in result['candidates']],
                         [c['operation_id'] for c in record['candidates']])
        refiner.assert_called_once()
        self.assertEqual(self.client.submit.call_count, 2)


if __name__ == '__main__':
    unittest.main()
