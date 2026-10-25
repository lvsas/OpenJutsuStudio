"""Local API round trips with synthetic bytes and mocked expensive dispatch only."""
import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import app as app_module
import config
import core
import engines
import job_api
import model_catalog
from take_capsule_api import freeze_take_capsule
from fastapi.testclient import TestClient


class InlineExecutor:
    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except BaseException as exc:
            future.set_exception(exc)
        return future


class ModelBindingAPITests(unittest.TestCase):
    def test_submit_and_capsule_replay_use_frozen_names_after_settings_and_metadata_change(self):
        aliases = {key: f'Renamed/{key} Exact Case.safetensors' for key in model_catalog.LTX_ROLES}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = root / 'synthetic-result.mp4'
            result.write_bytes(b'synthetic result')
            observed = []

            async def save_video(upload, destination, max_bytes):
                destination.write_bytes(await upload.read())
                return {'width': 704, 'height': 384, 'fps': 24, 'frames': 9, 'duration': 0.375}

            def runner(job, video, opts):
                # Exercise production engine forwarding and graph builders, not SDK/GPU.
                with patch.object(engines, '_run_graph', return_value='synthetic-output') as run:
                    engine = engines.LTXRippleEngine()
                    engine.edit_frame(None, 'image', job.prompt, **opts['edit'])
                    engine.propagate(None, 'video', 'image', opts['ripple_prompt'], **opts['propagate'])
                    observed.append([call.args[1] for call in run.call_args_list])

            target = SimpleNamespace(model_bindings=aliases)
            with patch.object(core, 'WORK', root), \
                 patch.object(app_module, 'MEDIA_DIR', root / 'media'), \
                 patch.object(config, 'compute_target', return_value=target), \
                 patch.object(app_module, '_EXECUTOR', InlineExecutor()), \
                 patch.object(app_module, 'PIPELINE_RUNNER', runner), \
                 patch.object(app_module, 'check_readiness', return_value={'ready': True, 'issues': []}) as preflight, \
                 patch.object(job_api, 'save_video', save_video):
                client = TestClient(app_module.app)
                response = client.post('/api/jobs', files={'video': ('synthetic.mp4', b'synthetic source', 'video/mp4')},
                                       data={'edit_prompt': 'synthetic test direction'})
                self.assertEqual(response.status_code, 202, response.text)
                parent = core.Job.load(response.json()['job_id'])
                self.assertEqual(parent.meta['take_recipe']['model_files'], aliases)
                parent.status, parent.result = 'done', str(result)
                parent.meta['shots'] = [{'start': 0, 'end': 8}]
                freeze_take_capsule(parent, result)
                # Capsule is authoritative even if non-frozen metadata changes later.
                parent.meta['take_recipe']['model_files']['flux_unet'] = 'Changed metadata.safetensors'
                parent.save()
                target.model_bindings = {key: f'Later/{key}.safetensors' for key in aliases}
                replay = client.post(f'/api/jobs/{parent.id}/replay')
                self.assertEqual(replay.status_code, 202, replay.text)
                graph = preflight.call_args.kwargs['required_graph']
                names = [node['inputs'].get('unet_name') for node in graph.values()]
                self.assertIn(aliases['flux_unet'], names)
                self.assertIn(aliases['ltx_unet'], names)
                self.assertNotIn(target.model_bindings['ltx_unet'], names)
                child = core.Job.load(replay.json()['job_id'])
                self.assertEqual(child.meta['take_recipe']['model_files'], aliases)
            self.assertEqual(len(observed), 2)
            for frame, ripple in observed:
                self.assertEqual(frame['70']['inputs']['unet_name'], aliases['flux_unet'])
                self.assertEqual(ripple['821']['inputs']['unet_name'], aliases['ltx_unet'])
                self.assertEqual(ripple['1312']['inputs']['lora_name'], aliases['ripple_lora'])

    def test_invalid_or_missing_frozen_bindings_refuse_replay_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, result = root / 'source.mp4', root / 'result.mp4'
            source.write_bytes(b'synthetic source')
            result.write_bytes(b'synthetic result')
            with patch.object(core, 'WORK', root), \
                 patch.object(app_module, 'PIPELINE_RUNNER') as runner:
                client = TestClient(app_module.app)
                for model_files in (None, {'unknown_role': 'synthetic.safetensors'},
                                    {'flux_unet': '../private-file.safetensors'}):
                    recipe = {'schema_version': 1, 'model_files': model_files}
                    parent = core.Job(id='invalid-bindings', status='done', video=str(source),
                                      result=str(result), meta={'take_recipe': recipe, 'shots': [{'start': 0, 'end': 8}]})
                    parent.save()
                    response = client.post(f'/api/jobs/{parent.id}/replay')
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertIn('frozen model bindings', response.text)
                    self.assertNotIn('private-file', response.text)
                runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
