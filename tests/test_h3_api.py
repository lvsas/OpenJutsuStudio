"""H3 HTTP contracts without GPU, external services, or app.py integration."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import core
import h3_api
from h3_capsule import freeze_capsule
from h3_recipe import bind_frames


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'media'
        self.media.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(core, 'WORK', self.root).start()
        self.ready = MagicMock(return_value={'ready': True, 'issues': []})
        self.dispatch = MagicMock()
        app = FastAPI()
        app.include_router(h3_api.create_router(lambda: self.media, 4096, self.ready, self.dispatch))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        async def save(video, destination, limit):
            destination.write_bytes(await video.read())
            return {'frames': 24, 'fps': 24, 'duration': 1, 'width': 64, 'height': 64}
        async def reference(upload, destination, limit):
            data = await upload.read()
            if not data or data == b'invalid':
                from fastapi import HTTPException
                raise HTTPException(422, 'Invalid reference')
            destination.write_bytes(data)
        patch.object(h3_api, 'save_video', side_effect=save).start()
        patch.object(h3_api, 'save_reference', side_effect=reference).start()


    def submit(self, reference=b'image', **kwargs):
        files = [('video', ('../../source.mp4', b'video', 'video/mp4'))]
        if reference is not None:
            files.append(('reference_image', ('../../ref.png', reference, 'image/png')))
        return self.client.post('/api/h3/jobs', files=files, **kwargs)

    def test_reference_required_invalid_and_valid(self):
        self.assertEqual(self.submit(None).status_code, 422)
        self.assertEqual(self.submit(b'invalid').status_code, 422)
        self.assertFalse(list(self.media.iterdir()))
        response = self.submit(data={'edit_prompt': '  exact\n', 'seed': '42'})
        self.assertEqual(response.status_code, 202, response.text)
        job, source, opts = self.dispatch.call_args.args
        self.assertEqual(self.client.get('/api/h3/readiness').json(), {'ready': True, 'issues': []})
        self.assertEqual(self.client.get(f'/api/h3/jobs/{job.id}/source').content, b'video')
        self.assertEqual(self.client.get(f'/api/h3/jobs/{job.id}/reference').content, b'image')
        self.assertEqual(job.engine, 'minimax-h3')
        self.assertEqual(opts['recipe']['user_edit_prompt'], '  exact\n')
        self.assertEqual(opts['recipe']['seed'], 42)
        self.assertEqual(source.parent, self.media)
        self.assertEqual(Path(opts['reference_image']).parent, self.media)
        self.assertNotIn(str(self.root), response.text)
        self.assertEqual(self.client.get(f'/api/h3/jobs/{job.id}/capsule').status_code, 409)

    def test_duplicate_reference_and_seed_bounds_are_rejected(self):
        response = self.client.post('/api/h3/jobs', files=[
            ('video', ('source.mp4', b'video', 'video/mp4')),
            ('reference_image', ('one.png', b'image', 'image/png')),
            ('reference_image', ('two.png', b'image', 'image/png'))])
        self.assertEqual(response.status_code, 422)
        for seed in ('-1', str(2**64)):
            self.assertEqual(self.submit(data={'seed': seed}).status_code, 422)
        self.dispatch.assert_not_called()

    def test_readiness_is_injected_and_no_dispatch_when_blocked(self):
        self.ready.return_value = {'ready': False, 'issues': ['H3 weights missing']}
        self.assertEqual(self.submit().status_code, 503)
        self.dispatch.assert_not_called()
        self.assertFalse(list(self.media.iterdir()))

    def test_single_shot_limit_documented_without_false_positive_cut_gate(self):
        response = self.submit()
        self.assertEqual(response.status_code, 202)
        self.assertIn('One continuous shot', response.text)
        job = self.dispatch.call_args.args[0]
        self.assertEqual(job.meta['source_shot_plan'], [{'start': 0, 'end': 23, 'fps': 24}])
        schema = self.client.get('/openapi.json').json()
        self.assertIn('Multi-cut editing is not', schema['paths']['/api/h3/jobs']['post']['description'])

    def test_replay_uses_frozen_recipe_and_no_inherited_success(self):
        self.submit()
        job, source, opts = self.dispatch.call_args.args
        recipe = bind_frames(opts['recipe'], 24)
        result = self.media / 'result.mp4'
        result.write_bytes(b'result')
        freeze_capsule(job, recipe, source, opts['reference_image'], result, self.media)
        job.status, job.result = 'done', str(result)
        job.save()
        response = self.client.get(f'/api/h3/jobs/{job.id}/capsule')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(str(self.root), response.text)
        self.dispatch.reset_mock()
        replay = self.client.post(f'/api/h3/jobs/{job.id}/replay')
        self.assertEqual(replay.status_code, 202, replay.text)
        child, replay_source, replay_opts = self.dispatch.call_args.args
        self.assertEqual(replay_opts['recipe'], recipe)
        self.assertEqual(replay_source, source)
        self.assertEqual(child.meta['parent_job_id'], job.id)
        self.assertEqual(child.status, 'queued')
        self.assertIsNone(child.result)
        self.assertNotIn('h3_capsule', child.meta)
        Path(opts['reference_image']).write_bytes(b'changed')
        self.assertEqual(self.client.post(f'/api/h3/jobs/{job.id}/replay').status_code, 409)

    def test_dispatch_failure_is_terminal(self):
        self.dispatch.side_effect = RuntimeError('executor unavailable')
        self.assertEqual(self.submit().status_code, 503)
        saved = core.Job.all()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].status, 'error')
        self.assertIsNotNone(saved[0].finished)


if __name__ == '__main__':
    unittest.main()
