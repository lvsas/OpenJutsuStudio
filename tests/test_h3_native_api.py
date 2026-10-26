"""Ordinary H3 HTTP native capture: explicit choice, no implicit replay or inference."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import test_h3_api as fixture
import core
import h3_api
import continuable_take_api
from h3_recipe import bind_frames


class NativeCaptureAPITests(unittest.TestCase):
    root: Path
    media: Path
    ready: MagicMock
    dispatch: MagicMock
    client: TestClient
    setUp = fixture.APITests.setUp
    submit = fixture.APITests.submit

    def configured(self, report=None):
        self.client.close()
        self.native_ready = MagicMock(return_value=report or {'ready':True,'issues':[]})
        app = FastAPI()
        app.include_router(h3_api.create_router(lambda:self.media,4096,self.ready,self.dispatch,
                           native_readiness_check=self.native_ready))
        app.include_router(continuable_take_api.create_router(lambda:self.root))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def completed(self):
        response = self.submit()
        self.assertEqual(response.status_code,202,response.text)
        job, source, opts = self.dispatch.call_args.args
        job.status = 'done'
        job.meta.update(native_take_id='a'*32,processed_frames=24)
        job.save()
        return job,source,opts

    def test_legacy_submission_stays_video_only(self):
        response = self.submit()
        self.assertEqual(response.status_code,202,response.text)
        self.assertIsNot(self.dispatch.call_args.args[2].get('native_capture'),True)

    def test_native_request_requires_configured_preflight_before_upload_or_job(self):
        self.assertEqual(self.submit(data={'native_capture':'true'}).status_code,503)
        self.dispatch.assert_not_called()
        self.assertEqual(list(self.media.iterdir()),[])
        self.assertFalse((self.root/'jobs').exists())

    def test_explicit_native_request_is_frozen_and_dispatched(self):
        self.configured()
        response = self.submit(data={'native_capture':'true'})
        self.assertEqual(response.status_code,202,response.text)
        job,_,opts = self.dispatch.call_args.args
        self.assertIs(opts['native_capture'],True)
        self.assertIs(core.Job.load(job.id).meta['native_capture_requested'],True)
        self.native_ready.assert_called_once()

    def test_native_missing_dependencies_refuse_without_work(self):
        self.configured({'ready':False,'issues':['Native saver is unavailable']})
        response = self.submit(data={'native_capture':'true'})
        self.assertEqual(response.status_code,503)
        self.dispatch.assert_not_called()
        self.assertEqual(list(self.media.iterdir()),[])
        self.assertFalse((self.root/'jobs').exists())

    def test_native_readiness_query_never_dispatches(self):
        self.configured()
        response=self.client.get('/api/h3/readiness?native_capture=true')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['ready'])
        self.native_ready.assert_called_once()
        self.dispatch.assert_not_called()
        self.assertEqual(list(self.media.iterdir()),[])

    def test_replay_capture_is_an_explicit_new_choice(self):
        self.configured()
        job,source,opts = self.completed()
        job.meta['native_capture_requested']=True
        job.save()
        before=job.path.read_bytes()
        recipe=bind_frames(copy.deepcopy(opts['recipe']),24,source_audio=False)
        references=opts['reference_images']
        with patch.object(h3_api,'replay_inputs',return_value=(recipe,source,references)):
            reply=self.client.post(f'/api/h3/jobs/{job.id}/replay',json={})
            self.assertEqual(reply.status_code,202,reply.text)
            self.assertIsNot(self.dispatch.call_args.args[2].get('native_capture'),True)
            reply=self.client.post(f'/api/h3/jobs/{job.id}/replay',json={'native_capture':True})
            self.assertEqual(reply.status_code,202,reply.text)
            self.assertIs(self.dispatch.call_args.args[2]['native_capture'],True)
        self.assertEqual(job.path.read_bytes(),before)

    def test_replay_rejects_non_boolean_capture(self):
        for bad in ('true',1,None):
            with self.subTest(value=bad):
                reply=self.client.post('/api/h3/jobs/'+'b'*32+'/replay',json={'native_capture':bad})
                self.assertEqual(reply.status_code,422,reply.text)
        self.dispatch.assert_not_called()

    def test_old_swap_native_state_is_not_fabricated(self):
        response=self.submit()
        job,_,_=self.dispatch.call_args.args
        job.status='done';job.save()
        reply=self.client.get(f'/api/h3/jobs/{job.id}/native-state')
        self.assertEqual(reply.status_code,200,reply.text)
        self.assertEqual(reply.json(),{'available':False})

    def test_native_state_checks_origin_and_returns_only_fixed_urls(self):
        self.configured()
        job,_,_=self.completed()
        capsule={'origin':{'source_job':job.id,'operator_label':'native-swap'},
                 'family':{'context':{'delivered_frames':56,'fps':24}}}
        record=SimpleNamespace(take_id='a'*32,to_manifest=lambda:copy.deepcopy(capsule))
        family=SimpleNamespace(record=record)
        with patch.object(h3_api,'get_validated_family',return_value=family):
            reply=self.client.get(f'/api/h3/jobs/{job.id}/native-state')
            self.assertEqual(reply.status_code,200,reply.text)
            result=reply.json()
            self.assertTrue(result['available'])
            self.assertEqual(result['take_id'],'a'*32)
            self.assertEqual(result['native_seconds'],56/24)
            self.assertEqual(result['display_seconds'],1)
            self.assertEqual(result['urls']['mctx'],'/api/continuity/takes/'+'a'*32+'/artifacts/mctx')
            self.assertNotIn(str(self.root),reply.text)
            capsule['origin']['source_job']='different-job'
            self.assertEqual(self.client.get(f'/api/h3/jobs/{job.id}/native-state').status_code,409)

    def test_private_family_downloads_are_validated_and_role_bounded(self):
        self.configured()
        paths={}
        for role,suffix in [('video','.mp4'),('mctx','.mctx.safetensors'),('conditioning','.cond.safetensors')]:
            path=self.media/('fixture'+suffix);path.write_bytes(role.encode());paths[role]=path
        family=SimpleNamespace(**paths)
        with patch.object(continuable_take_api,'get_validated_family',return_value=family) as validate:
            for role,path in paths.items():
                reply=self.client.get('/api/continuity/takes/'+'a'*32+'/artifacts/'+role)
                self.assertEqual(reply.status_code,200,reply.text)
                self.assertEqual(reply.content,path.read_bytes())
                self.assertIn('attachment',reply.headers['content-disposition'])
                self.assertIn('no-store',reply.headers['cache-control'])
            self.assertEqual(validate.call_count,3)
            validate.reset_mock()
            self.assertEqual(self.client.get('/api/continuity/takes/'+'a'*32+'/artifacts/unknown').status_code,422)
            validate.assert_not_called()
        with patch.object(continuable_take_api,'get_validated_family',side_effect=ValueError('private diagnostic')):
            reply=self.client.get('/api/continuity/takes/'+'a'*32+'/artifacts/mctx')
            self.assertEqual(reply.status_code,409)
            self.assertNotIn('private diagnostic',reply.text)


if __name__=='__main__':
    unittest.main()
