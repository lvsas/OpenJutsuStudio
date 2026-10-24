"""Position drafts share the existing revisioned project; no compute or second store."""
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
import continuable_take
from test_timeline_store import IsolatedTimeline
from timeline_api import create_router

class PositionDraftTests(IsolatedTimeline):
    def setUp(self):
        super().setUp()
        app=FastAPI()
        app.include_router(create_router(lambda:self.work,lambda:self.media,2_000_000))
        self.client=self.enterContext(TestClient(app))
        project=self.client.post('/api/timeline/projects',json={'title':'Positions'}).json()
        self.url='/api/timeline/projects/'+project['project_id']+'/native-workspace'
        self.enterContext(patch.object(continuable_take,'get_take',return_value=object()))
        self.key='root:start:end'
        self.payload={'revision':0,'placements':[],'selected_placement_id':None,'drafts':{},
            'selected_position':self.key,'position_drafts':{self.key:{'mode':'root','prompt':'A new shot',
            'seed':'18446744073709551615','raw_frames':124,'reference_ids':['a'*32],
            'width':1024,'height':576,'count':2,'reference_mode':'custom'}}}

    def test_root_roundtrip_preserves_reference_order_and_exact_seed(self):
        r=self.client.patch(self.url,json=self.payload)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['position_drafts'],self.payload['position_drafts'])
        self.assertEqual(self.client.get(self.url).json(),r.json())

    def test_legacy_patch_does_not_erase_position_drafts(self):
        self.assertEqual(self.client.patch(self.url,json=self.payload).status_code,200)
        r=self.client.patch(self.url,json={'revision':1,'placements':[],
            'selected_placement_id':None,'drafts':{}})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['position_drafts'],self.payload['position_drafts'])

    def test_invalid_position_mode_geometry_and_ids_do_not_write(self):
        import copy
        for change in ({'selected_position':'bridge:start:end'},
                       {'selected_position':'root:../bad:end'},
                       {'position_drafts':{self.key:{**self.payload['position_drafts'][self.key],'width':True}}},
                       {'position_drafts':{self.key:{**self.payload['position_drafts'][self.key],'reference_ids':['../bad']}}}):
            with self.subTest(change=change):
                body={**copy.deepcopy(self.payload),**change}
                self.assertEqual(self.client.patch(self.url,json=body).status_code,422)
        self.assertEqual(self.client.get(self.url).json()['revision'],0)

    def test_stale_revision_preserves_saved_root_draft(self):
        self.assertEqual(self.client.patch(self.url,json=self.payload).status_code,200)
        before=self.client.get(self.url).json()
        self.assertEqual(self.client.patch(self.url,json=self.payload).status_code,409)
        self.assertEqual(self.client.get(self.url).json(),before)
