from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_timeline_store import IsolatedTimeline
from timeline_api import create_router
from timeline_store import TimelineStore

class ProjectAssetsTests(IsolatedTimeline):
    def setUp(self):
        super().setUp();app=FastAPI();app.include_router(create_router(lambda:self.work,lambda:self.media,2_000_000))
        self.client=self.enterContext(TestClient(app));self.project=self.store.create('A');self.other=self.store.create('B')
        self.project_id=self.project['project_id'];self.url='/api/timeline/projects/'+self.project_id+'/assets'

    def attach(self,kind,id,revision=0):
        return self.client.post(self.url,json={'revision':revision,'kind':kind,'asset_id':id})

    def test_old_project_read_is_readonly_and_path_free(self):
        p=self.store._path('projects',self.project_id);before=p.read_bytes();stamp=p.stat().st_mtime_ns
        r=self.client.get(self.url);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['assets'],{'characters':[],'jobs':[],'takes':[]})
        self.assertEqual(p.read_bytes(),before);self.assertEqual(p.stat().st_mtime_ns,stamp)

    def test_roles_reopen_duplicate_and_two_project_isolation(self):
        char=self.job(self.media/'not-consumed.png',engine='flux3-klein-character');video=self.job(self.media/'not-consumed.mp4')
        jobbytes=char.path.read_bytes()
        r=self.attach('character',char.id);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['revision'],1)
        r=self.attach('job',video.id,1);self.assertEqual(r.status_code,200,r.text)
        r=self.attach('job',video.id,2);self.assertEqual(r.json()['revision'],2)
        fresh=TimelineStore(self.work,self.media,2_000_000).get_assets(self.project_id)
        self.assertEqual(fresh['assets'],{'characters':[char.id],'jobs':[video.id],'takes':[]})
        self.assertEqual(self.store.get_assets(self.other['project_id'])['assets']['jobs'],[])
        self.assertEqual(char.path.read_bytes(),jobbytes)
        self.assertNotIn(str(self.work),r.text)

    def test_invalid_role_missing_id_extra_fields_and_stale_write_do_not_mutate(self):
        video=self.job(self.media/'not-consumed.mp4');p=self.store._path('projects',self.project_id);before=p.read_bytes()
        for data in [dict(revision=True,kind='job',asset_id=video.id),dict(revision=0,kind='character',asset_id=video.id),dict(revision=0,kind='job',asset_id='../bad'),dict(revision=0,kind='job',asset_id=video.id,path='/private')]:
            r=self.client.post(self.url,json=data);self.assertEqual(r.status_code,422,r.text);self.assertEqual(p.read_bytes(),before)
        self.assertEqual(self.attach('job','f'*32).status_code,404);self.assertEqual(p.read_bytes(),before)
        self.assertEqual(self.attach('job',video.id).status_code,200)
        after=p.read_bytes();self.assertEqual(self.attach('job',video.id).status_code,409);self.assertEqual(p.read_bytes(),after)

    def test_explicit_placement_keeps_membership_after_remove_without_placing_in_other_project(self):
        take='a'*32;url=self.url.removesuffix('/assets')+'/native-workspace'
        body={'revision':0,'placements':[{'placement_id':'b'*32,'take_id':take}], 'selected_placement_id':'b'*32,'drafts':{}}
        with patch('continuable_take.get_take',return_value=object()):
            r=self.client.patch(url,json=body);self.assertEqual(r.status_code,200,r.text)
            body.update(revision=1,placements=[],selected_placement_id=None)
            self.assertEqual(self.client.patch(url,json=body).status_code,200)
        self.assertEqual(self.client.get(self.url).json()['assets']['takes'],[take])
        self.assertEqual(self.store.get_assets(self.other['project_id'])['assets']['takes'],[])
        self.assertEqual(self.store.get_native_workspace(self.project_id)['placements'],[])

    def test_common_library_is_readonly_safe_and_sorted(self):
        one=self.job(self.media/'not-consumed.mp4');one.created=2;one.meta['private_prompt']='must-not-leak';one.save()
        two=self.job(self.media/'not-consumed.png',engine='flux3-klein-character');two.created=5;two.save()
        before={p:p.read_bytes() for p in (self.work/'jobs').glob('*.json')}
        result=self.client.get('/api/timeline/library');self.assertEqual(result.status_code,200,result.text)
        self.assertEqual([row['job_id'] for row in result.json()['jobs']],[two.id,one.id])
        self.assertNotIn('must-not-leak',result.text);self.assertNotIn(str(self.work),result.text)
        self.assertEqual({p:p.read_bytes() for p in before},before)

    def test_reference_and_direction_drafts_stay_isolated(self):
        url=self.url.removesuffix('/assets')+'/native-workspace';take='a'*32;placement='b'*32
        body={'revision':0,'placements':[{'placement_id':placement,'take_id':take}], 'selected_placement_id':placement,'drafts':{placement:{'prompt':'Only A','seed':'18446744073709551615','raw_frames':158}}}
        with patch('continuable_take.get_take',return_value=object()):self.assertEqual(self.client.patch(url,json=body).status_code,200)
        self.assertEqual(self.store.get_native_workspace(self.other['project_id'])['drafts'],{})
        self.assertEqual(self.store.get_native_workspace(self.project_id)['drafts'][placement]['seed'],'18446744073709551615')
