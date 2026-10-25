"""Project organization never deletes or rewrites its source assets."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from timeline_api import create_router
from timeline_models import AssociateAsset
from timeline_store import TimelineError, read_json, atomic_json
from test_timeline_store import IsolatedTimeline


class ProjectLifecycleTests(IsolatedTimeline):
    def setup_project(self):
        project = self.store.create('Selected project')
        video = self.media / 'result.mp4'
        video.write_bytes(b'not decoded during organization')
        job = self.job(video)
        job.meta['origin_project_id'] = project['project_id']
        job.save()
        return project, job, video

    def test_remove_origin_membership_persists_without_touching_job_or_media(self):
        project, job, video = self.setup_project()
        before = (self.work / 'jobs' / (job.id + '.json')).read_bytes(), video.read_bytes()
        result = self.store.dissociate_asset(project['project_id'], AssociateAsset(revision=0,kind='job',asset_id=job.id))
        self.assertNotIn(job.id, result['assets']['jobs'])
        self.assertEqual(result['revision'], 1)
        self.assertNotIn(job.id, self.store.get_assets(project['project_id'])['assets']['jobs'])
        self.assertIn(job.id, [r['job_id'] for r in self.store.library_jobs()])
        self.assertEqual(before, ((self.work/'jobs'/(job.id+'.json')).read_bytes(), video.read_bytes()))
        restored = self.store.associate_asset(project['project_id'], AssociateAsset(revision=1,kind='job',asset_id=job.id))
        self.assertIn(job.id, restored['assets']['jobs'])
        self.assertEqual(restored['revision'],2)

    def test_remove_refuses_placed_source_and_revision_conflicts(self):
        project, job, _ = self.setup_project()
        path = self.store._path('projects',project['project_id'])
        raw=read_json(path)
        raw['native_workspace']={'placements':[{'placement_id':'a'*32,'take_id':job.id,'source_kind':'swap'}],'drafts':{}}
        atomic_json(path,raw)
        before=path.read_bytes()
        for revision in (0,9):
            with self.assertRaises(TimelineError) as raised:
                self.store.dissociate_asset(project['project_id'],AssociateAsset(revision=revision,kind='job',asset_id=job.id))
            self.assertEqual(raised.exception.status_code,409)
            self.assertEqual(path.read_bytes(),before)

    def test_archive_restore_preserves_resources_and_other_project(self):
        project,job,video=self.setup_project()
        other=self.store.create('Other project')
        other_path=self.store._path('projects',other['project_id'])
        before=other_path.read_bytes(),video.read_bytes()
        archived=self.store.set_archived(project['project_id'],0,True)
        self.assertTrue(archived['archived'])
        self.assertNotIn(project['project_id'],[p['project_id'] for p in self.store.list_projects()])
        self.assertIn(project['project_id'],[p['project_id'] for p in self.store.list_projects(archived=True)])
        self.assertIn(job.id,self.store.get_assets(project['project_id'])['assets']['jobs'])
        self.assertEqual(before,(other_path.read_bytes(),video.read_bytes()))
        restored=self.store.set_archived(project['project_id'],1,False)
        self.assertFalse(restored.get('archived',False))
        self.assertIn(project['project_id'],[p['project_id'] for p in self.store.list_projects()])
        with self.assertRaises(TimelineError):self.store.set_archived(project['project_id'],1,True)

    def test_archived_project_refuses_generation_and_editing_without_deleting_media(self):
        from project_scope import submission_project, validate_project
        from fastapi import HTTPException
        from timeline_models import RenameProject
        project,job,video=self.setup_project()
        archived=self.store.set_archived(project['project_id'],0,True)
        before=video.read_bytes()
        with self.assertRaises(HTTPException) as raised:
            submission_project(project['project_id'],self.media)
        self.assertEqual(raised.exception.status_code,409)
        with self.assertRaises(HTTPException):validate_project(self.work,project['project_id'])
        with self.assertRaises(TimelineError):self.store.rename(project['project_id'],archived['revision'],'No change')
        self.assertEqual(video.read_bytes(),before)
        self.assertEqual(self.store.get(project['project_id'])['title'],'Selected project')

    def test_native_resource_removal_also_hides_its_linked_origin_job(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        project,job,video=self.setup_project()
        take_id='b'*32
        record=SimpleNamespace(to_manifest=lambda:{'origin':{'source_job':job.id}})
        with patch('continuable_take.get_take',return_value=record):
            attached=self.store.associate_asset(project['project_id'],AssociateAsset(revision=0,kind='take',asset_id=take_id))
            removed=self.store.dissociate_asset(project['project_id'],AssociateAsset(revision=attached['revision'],kind='take',asset_id=take_id))
        self.assertNotIn(take_id,removed['assets']['takes'])
        self.assertNotIn(job.id,removed['assets']['jobs'])
        self.assertTrue(video.is_file())
        self.assertIn(job.id,[row['job_id'] for row in self.store.library_jobs()])

    def test_draft_is_not_archived(self):
        draft=self.store.draft(create=True)
        with self.assertRaises(TimelineError):self.store.set_archived(draft['project_id'],draft['revision'],True)
        self.assertEqual(self.store.draft()['project_id'],draft['project_id'])

    def test_http_routes_revision_and_read_only_archive_listing(self):
        project,job,_=self.setup_project()
        app=FastAPI();app.include_router(create_router(lambda:self.work,lambda:self.media,2_000_000))
        with TestClient(app) as client:
            base='/api/timeline/projects/'+project['project_id']
            r=client.post(base+'/assets/remove',json={'revision':0,'kind':'job','asset_id':job.id})
            self.assertEqual(r.status_code,200,r.text)
            r=client.post(base+'/archive',json={'revision':1});self.assertEqual(r.status_code,200,r.text)
            path=self.store._path('projects',project['project_id']);before=path.read_bytes()
            rows=client.get('/api/timeline/projects?archived=true').json()['projects']
            self.assertIn(project['project_id'],[p['project_id'] for p in rows])
            self.assertEqual(path.read_bytes(),before)
            r=client.post(base+'/restore',json={'revision':2});self.assertEqual(r.status_code,200,r.text)
