"""HTTP settings, credential privacy, activation leases and read-only probes."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from compute_activity import Activity, ActivityMiddleware, LeasedExecutor
from compute_settings import SettingsError, Store
from compute_settings_api import create_router


class SettingsAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'work';self.activity=Activity()
        self.probe=MagicMock(return_value={'connected':True,'ready':False,'mode':'remote-self-hosted',
                                          'engines':{},'issues':[],'warnings':['Inventory is unknown.']})
        app=FastAPI();app.add_middleware(ActivityMiddleware,activity=self.activity)
        app.include_router(create_router(lambda:self.root,self.activity,self.probe))
        self.client=TestClient(app);self.addCleanup(self.client.close)

    def save(self,**kwargs):
        return self.client.put('/api/settings/compute',json={'revision':0,'base_url':'http://localhost:9000',**kwargs})

    def test_get_creates_nothing_and_explicit_probe_does_not_save(self):
        response=self.client.get('/api/settings/compute')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.probe.assert_not_called();self.assertFalse(self.root.exists())
        response=self.client.post('/api/settings/compute/test',json={'base_url':'http://localhost:9000'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['connected']);self.assertFalse(response.json()['ready'])
        self.assertFalse(self.root.exists())

    def test_save_then_reload_is_redacted(self):
        response=self.save(api_key='private-settings-value')
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('private-settings-value',response.text)
        self.assertTrue(response.json()['api_key_configured'])
        self.assertEqual(self.client.get('/api/settings/compute').json(),response.json())
        self.probe.assert_not_called()
        self.assertEqual(self.save().status_code,409)

    def test_cross_origin_bad_types_duplicates_and_error_values_never_echo_keys(self):
        self.assertEqual(self.client.put('/api/settings/compute',json={'revision':0,'base_url':'http://localhost:9000'},
                                         headers={'Origin':'https://untrusted.example'}).status_code,403)
        for body in ({'revision':True,'base_url':'http://localhost'}, {'revision':0,'base_url':'http://localhost','api_key':['private-settings-value']},
                     {'revision':0,'base_url':'http://localhost','api_key':'private-settings-value\n'},
                     {'revision':0,'base_url':'http://localhost','api_key':'private-settings-value','extra':True}):
            response=self.client.put('/api/settings/compute',json=body)
            self.assertEqual(response.status_code,422,response.text)
            self.assertNotIn('private-settings-value',response.text)
        response=self.client.put('/api/settings/compute',content='{"revision":0,"revision":0,"base_url":"http://localhost"}')
        self.assertEqual(response.status_code,422)

    def test_activation_refused_during_request_or_native_work(self):
        release=self.activity.acquire()
        self.assertEqual(self.save().status_code,409)
        self.assertFalse(self.root.exists());release()
        self.activity.extra_busy=lambda:True
        self.assertEqual(self.save().status_code,409)
        self.activity.extra_busy=lambda:False
        self.assertEqual(self.save().status_code,200)

    def test_executor_holds_lease_until_queued_and_running_work_finishes(self):
        started=threading.Event();finish=threading.Event()
        with LeasedExecutor(max_workers=1,activity=self.activity) as executor:
            first=executor.submit(lambda:(started.set(),finish.wait(5)))
            self.assertTrue(started.wait(2))
            second=executor.submit(lambda:True)
            self.assertEqual(self.save().status_code,409)
            finish.set();first.result(5);second.result(5)
        self.assertEqual(self.activity.count,0)
        self.assertEqual(self.save().status_code,200)

    def test_failed_probe_is_generic_and_does_not_write(self):
        self.probe.side_effect=RuntimeError('private-settings-value')
        response=self.client.post('/api/settings/compute/test',json={'base_url':'http://localhost:9000'})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private-settings-value',response.text)
        self.assertFalse(self.root.exists())


if __name__=='__main__':unittest.main()
