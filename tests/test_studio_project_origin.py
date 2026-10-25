"""Project origin is tested with isolated stores and fake compute, never live inference."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import core
from timeline_store import TimelineStore
import test_character_api as character_fixture
from test_timeline_store import IsolatedTimeline
from timeline_api import create_router
from continuity_attempts import create_or_get, AttemptConflict

class StudioOriginTests(unittest.TestCase):
    setUp=character_fixture.CharacterAPITests.setUp
    submit=character_fixture.CharacterAPITests.submit
    completed=character_fixture.CharacterAPITests.completed
    def test_explicit_origin_frozen_before_dispatch_and_resume_from_store(self):
        store=TimelineStore(self.root,self.media,1);a=store.create('A');b=store.create('B')
        r=self.submit(project_id=a['project_id']);self.assertEqual(r.status_code,202,r.text)
        job=self.dispatch.call_args.args[0]
        self.assertEqual(job.meta['origin_project_id'],a['project_id'])
        self.assertEqual(core.Job.load(job.id).meta['origin_project_id'],a['project_id'])
        self.assertEqual(r.json()['project_id'],a['project_id'])
        self.assertEqual(store.get_assets(b['project_id'])['assets']['characters'],[])
        self.assertEqual(store.get_assets(a['project_id'])['jobs'][0]['job_id'],job.id)
        self.assertEqual(store.get_assets(a['project_id'])['revision'],0)

    def test_bad_project_refused_before_readiness_or_dispatch(self):
        for owner,status in [('../private',422),('f'*32,404),(True,422)]:
            self.ready.reset_mock();self.dispatch.reset_mock()
            response=self.submit(project_id=owner);self.assertEqual(response.status_code,status,response.text)
            self.ready.assert_not_called();self.dispatch.assert_not_called()

    def test_replay_in_b_preserves_parent_origin_and_bytes(self):
        parent=self.completed();store=TimelineStore(self.root,self.media,1);b=store.create('B')
        before=parent.path.read_bytes()
        result=self.client.post('/api/characters/jobs/'+parent.id+'/replay',json={'project_id':b['project_id']})
        self.assertEqual(result.status_code,202,result.text)
        child=self.dispatch.call_args.args[0];self.assertEqual(child.meta['origin_project_id'],b['project_id'])
        self.assertEqual(parent.path.read_bytes(),before)


class VideoStudioOriginTests(IsolatedTimeline):
    def test_both_video_studios_freeze_before_fake_dispatch_and_reject_bad_scope_before_upload(self):
        import job_api, h3_api
        a=self.store.create('A');b=self.store.create('B')
        ready=MagicMock(return_value={'ready':True,'issues':[]})
        dispatch=MagicMock();info={'width':640,'height':360,'fps':24,'frames':24,'duration':1}
        app=FastAPI();app.include_router(job_api.create_router(lambda:self.media,2_000_000,ready,dispatch,'ltx25-ripple'))
        app.include_router(h3_api.create_router(lambda:self.media,2_000_000,ready,dispatch))
        client=self.enterContext(TestClient(app))
        with patch('job_api._store_uploads',new=AsyncMock(return_value=(info,self.media/'source.mp4',[]))) as uploads:
            r=client.post('/api/jobs',data={'project_id':a['project_id'],'edit_prompt':'Change the character'},files={'video':('source.mp4',b'fixture','video/mp4')})
            self.assertEqual(r.status_code,202,r.text);job=dispatch.call_args.args[0]
            self.assertEqual(core.Job.load(job.id).meta['origin_project_id'],a['project_id'])
            self.assertEqual(r.json()['job']['project_id'],a['project_id'])
            ready.reset_mock();uploads.reset_mock()
            r=client.post('/api/jobs',data={'project_id':'f'*32,'edit_prompt':'Change the character'},files={'video':('source.mp4',b'fixture','video/mp4')})
            self.assertEqual(r.status_code,404,r.text);uploads.assert_not_called();ready.assert_not_called()
        with patch('h3_api.probe_source', return_value=info),patch('h3_api.save_video',new=AsyncMock(return_value=info)),patch('h3_api.save_reference',new=AsyncMock()),patch('h3_api._dispatch_options',return_value={}):
            r=client.post('/api/h3/jobs',data={'project_id':b['project_id']},files=[('video',('source.mp4',b'fixture','video/mp4')),('reference_images',('reference.png',b'fixture','image/png'))])
            self.assertEqual(r.status_code,202,r.text);job=dispatch.call_args.args[0]
            self.assertEqual(core.Job.load(job.id).meta['origin_project_id'],b['project_id'])
            self.assertEqual(r.json()['project_id'],b['project_id'])
        self.assertEqual(len(self.store.get_assets(a['project_id'])['assets']['jobs']),1)
        self.assertEqual(len(self.store.get_assets(b['project_id'])['assets']['jobs']),1)


class ReplayProjectOriginTests(IsolatedTimeline):
    def test_ltx_replay_freezes_new_project_without_changing_parent(self):
        import take_capsule_api
        a=self.store.create('A');b=self.store.create('B')
        parent=core.Job(id='d'*32,status='done',result='not-read',meta={'origin_project_id':a['project_id']});parent.save()
        before=parent.path.read_bytes();dispatch=MagicMock()
        app=FastAPI();app.include_router(take_capsule_api.create_router(dispatch,lambda:{'ready':True}))
        client=self.enterContext(TestClient(app))
        with patch('take_capsule_api._replay_inputs',return_value=({},self.media/'source.mp4',[],[])),patch('take_capsule_api._replay_options',return_value={}):
            result=client.post('/api/jobs/'+parent.id+'/replay',json={'project_id':b['project_id']})
        self.assertEqual(result.status_code,202,result.text)
        child=dispatch.call_args.args[0]
        self.assertEqual(core.Job.load(child.id).meta['origin_project_id'],b['project_id'])
        self.assertEqual(parent.path.read_bytes(),before)
        self.assertEqual(result.json()['project_id'],b['project_id'])


class DraftScopeTests(IsolatedTimeline):
    def setUp(self):
        super().setUp();app=FastAPI();app.include_router(create_router(lambda:self.work,lambda:self.media,1))
        self.client=self.enterContext(TestClient(app))

    def test_read_does_not_create_and_repeated_post_reuses_unique_draft(self):
        self.assertIsNone(self.client.get('/api/timeline/draft').json()['project'])
        self.assertEqual(self.store.list_projects(),[])
        one=self.client.post('/api/timeline/draft',json={}).json()['project']
        two=self.client.post('/api/timeline/draft',json={}).json()['project']
        self.assertEqual(one,two);self.assertTrue(one['is_draft'])
        self.assertEqual(len(self.store.list_projects()),1)
        self.assertEqual(self.client.post('/api/timeline/draft',json={'title':'oops'}).status_code,422)

    def test_name_preserves_identity_and_new_draft_created_only_on_explicit_post(self):
        one=self.client.post('/api/timeline/draft',json={}).json()['project']
        result=self.client.patch('/api/timeline/projects/'+one['project_id']+'/name',json={'revision':0,'title':'My creation'})
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['project_id'],one['project_id'])
        self.assertFalse(result.json()['is_draft'])
        self.assertEqual(self.client.patch('/api/timeline/projects/'+one['project_id']+'/name',json={'revision':0,'title':'Stale'}).status_code,409)
        self.assertIsNone(self.client.get('/api/timeline/draft').json()['project']);self.assertEqual(len(self.store.list_projects()),1)
        two=self.client.post('/api/timeline/draft',json={}).json()['project'];self.assertNotEqual(one['project_id'],two['project_id'])
        self.assertEqual(self.store.get(one['project_id'])['title'],'My creation')

    def test_native_scope_is_part_of_atomic_idempotent_intent_and_candidate_membership(self):
        import continuity_attempts as attempts
        a=self.store.create('A');b=self.store.create('B');root=self.work/'native-attempts'
        args=dict(take_id='a'*32,request_id='b'*32,prompt='Continue',raw_frames=141,seeds=[18446744073709551615])
        first,created=create_or_get(root,project_id=a['project_id'],**args);self.assertTrue(created)
        again,created=create_or_get(root,project_id=a['project_id'],**args);self.assertFalse(created)
        with self.assertRaises(AttemptConflict):create_or_get(root,project_id=b['project_id'],**args)
        attempts._update(root,first['attempt_id'],lambda value:value['candidates'][0].update(status='done',take_id='c'*32))
        self.assertEqual(self.store.get_assets(a['project_id'])['assets']['takes'],['c'*32])
        self.assertEqual(self.store.get_assets(b['project_id'])['assets']['takes'],[])
        self.assertEqual(again['candidates'][0]['seed'],18446744073709551615)
