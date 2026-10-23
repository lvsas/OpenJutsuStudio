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
        with self.assertRaisesRegex(ValueError, 'at least 1.625 s'):
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
                target_fingerprint='f' * 64, work_root='/operations',
                inventory=lambda graph: ([], []))

    def test_a_take_below_the_pin_window_costs_no_upload_and_no_submission(self):
        client = MagicMock()
        with self.assertRaisesRegex(ValueError, 'at least 1.625 s'):
            self.submit(client, delivered=PIN_WINDOW - 1)
        client.assets.from_file.assert_not_called()
        client.run.assert_not_called()
        client.submit.assert_not_called()

    def test_a_non_24fps_take_is_refused_before_any_client_call(self):
        client = MagicMock()
        with self.assertRaisesRegex(ValueError, '24 fps'):
            self.submit(client, fps=30.0)
        client.run.assert_not_called()

    def test_a_missing_target_dependency_costs_no_upload_and_no_submission(self):
        client = MagicMock()
        with self.assertRaises(pipeline.TargetMissingDependencies) as error:
            with patch.object(pipeline, 'get_validated_family', return_value=family()), \
                    patch.object(pipeline, 'get_take', return_value=TAKE):
                pipeline.submit_forward(
                    '/work', TAKE.take_id, self.request(), client=client, models=MODELS,
                    references=[{'__type': 'core/ASSET', 'info': {'id': 'ref'}}],
                    target_fingerprint='f' * 64, work_root='/operations',
                    inventory=lambda graph: (['SomeMissingNode'], ['H3/missing.safetensors']))
        self.assertIn('H3/missing.safetensors', str(error.exception))
        self.assertIn('continuation was not submitted', str(error.exception))
        client.assets.from_file.assert_not_called()
        client.run.assert_not_called()
        client.submit.assert_not_called()

    def test_the_target_is_asked_before_the_parent_is_uploaded(self):
        client = MagicMock()
        seen = {}
        def inventory(graph):
            seen['uploaded_before_check'] = client.assets.from_file.called
            seen['graph_nodes'] = len(graph)
            return [], []
        with patch.object(pipeline, 'get_validated_family', return_value=family()), \
                patch.object(pipeline, 'get_take', return_value=TAKE), \
                patch.object(pipeline, 'restage_parent', return_value='isolated/take.mp4'), \
                patch.object(pipeline, 'create_operation'), \
                patch.object(pipeline, 'collect_forward'), \
                patch.object(pipeline, 'execute_operation', return_value={'status': 'queued'}):
            pipeline.submit_forward(
                '/work', TAKE.take_id, self.request(), client=client, models=MODELS,
                references=[{'__type': 'core/ASSET', 'info': {'id': 'ref'}}],
                target_fingerprint='f' * 64, work_root='/operations', inventory=inventory)
        self.assertFalse(seen['uploaded_before_check'],
                         'the inventory gate must run before the parent upload')
        self.assertGreater(seen['graph_nodes'], 50)

    def test_early_preflight_checks_generation_and_prompt_models_read_only(self):
        from unittest.mock import Mock
        inventory = Mock(side_effect=[([], []), ([], ['missing-text-model.safetensors'])])
        with patch.object(pipeline, 'get_validated_family', return_value=family()), \
                self.assertRaises(pipeline.TargetMissingDependencies):
            pipeline.preflight_continuation('/work', TAKE.take_id, models=MODELS,
                direction='Continue walking', reference_count=2, inventory=inventory)
        self.assertEqual(inventory.call_count, 2)
        first, second = [call.args[0] for call in inventory.call_args_list]
        self.assertIn('native_family', first)
        self.assertIn('prompt_text', second)
        self.assertFalse(any('style' in str(n.get('inputs', {}).get('lora_name', ''))
                             for n in first.values()))

    def test_production_hunt_checks_inventory_before_client_upload_or_refine(self):
        import ast
        from unittest.mock import Mock
        source = Path(__file__).resolve().parents[1] / 'src/app.py'
        function = next(n for n in ast.parse(source.read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name == '_hunt_refine')
        preflight = Mock(side_effect=pipeline.TargetMissingDependencies(['UnavailableNode']))
        client = Mock()
        refine = Mock()
        namespace = {'core': SimpleNamespace(WORK='/work'),
                     'parent_references': lambda *a: [Path('/ref.png')],
                     '_continuity_models': lambda: MODELS,
                     'preflight_continuation': preflight,
                     'make_client': client, 'refine_prompt': refine}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        with self.assertRaises(pipeline.TargetMissingDependencies):
            namespace['_hunt_refine']('Continue moving', TAKE.take_id)
        preflight.assert_called_once()
        client.assert_not_called()
        refine.assert_not_called()

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
        with self.assertRaisesRegex(ValueError, 'extending needs'):
            pipeline.parent_context(types.SimpleNamespace(artifacts=measured))


class RestageNamingTests(unittest.TestCase):
    """Requested upload names must not be confused with SDK-resolved locations."""

    def test_real_sdk_dedup_reuses_old_asset_ids_despite_unique_requested_names(self):
        import tempfile
        from comfy_sdk.assets import AssetFactory
        from comfy_sdk import _hashing

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / name for name in ('take.mp4', 'take.mctx.safetensors',
                                             'take.cond.safetensors')]
            old_names = ('take (1).mp4', 'take.mctx (1).safetensors',
                         'take.cond (1).safetensors')
            existing = {}
            for index, (path, name) in enumerate(zip(paths, old_names)):
                path.write_bytes(f'unit role {index}'.encode())
                digest = _hashing.hash_file(str(path))
                existing[digest] = SimpleNamespace(
                    id=f'existing-{index}', hash=digest, created_new=False,
                    url='http://unit.invalid/content', job_id=None, expires_at=None,
                    comfy_ref={'filename': name, 'subfolder': '', 'type': 'input'})
            low = MagicMock()
            low.head_asset_by_hash.side_effect = lambda digest: digest in existing
            low.asset_from_hash.side_effect = lambda digest, **kwargs: existing[digest]
            client = MagicMock()
            # Exercise actual SDK hashing and its by-hash branch, not a fake
            # from_file() that assumes the requested path wins.
            client.assets = AssetFactory(low)
            client.workflows.from_json.side_effect = lambda graph: graph
            client.run.return_value = SimpleNamespace(status='succeeded')
            artifacts = SimpleNamespace(video=paths[0], mctx=paths[1], conditioning=paths[2])
            with patch.object(pipeline, 'read_clip_handle', return_value='verified/take.mp4'):
                self.assertEqual(pipeline.restage_parent(client, artifacts, 'a' * 32),
                                 'verified/take.mp4')
            low.post_assets.assert_not_called()
            self.assertEqual(low.asset_from_hash.call_count, 3)
            requested = [call.kwargs['file_path'] for call in low.asset_from_hash.call_args_list]
            self.assertEqual(requested, ['a' * 32 + suffix for suffix in
                             ('.mp4', '.mctx.safetensors', '.cond.safetensors')])
            graph = client.run.call_args.args[0]
            for index, role in enumerate(('video', 'mctx', 'conditioning')):
                reference = graph['native_family']['inputs'][role]
                self.assertEqual(reference, {'__type': 'core/ASSET',
                                             'info': {'id': f'existing-{index}'}})
                # The stored proxy record, not file_path, owns this location.
                old = next(asset for asset in existing.values() if asset.id == reference['info']['id'])
                self.assertEqual(old.comfy_ref['filename'], old_names[index])
                self.assertEqual(paths[index].read_bytes(), f'unit role {index}'.encode())

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
