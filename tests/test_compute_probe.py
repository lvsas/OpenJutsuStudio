"""Connection tests measure transport/inventory, never a generation."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from compute_settings import Target
import compute_probe
import readiness


def inventory():
    info={}
    for graph in compute_probe._graphs().values():
        for node in graph.values():
            specs=info.setdefault(node['class_type'],{'input':{'required':{}}})['input']['required']
            for key,value in node['inputs'].items():
                if key in {'unet_name','clip_name','vae_name','lora_name','model_name'} and isinstance(value,str):
                    specs.setdefault(key,[[],{}])[0].append(value)
    return info


class ProbeTests(unittest.TestCase):
    def setUp(self):
        readiness._OBJECT_INFO_CACHE.clear()
        self.addCleanup(readiness._OBJECT_INFO_CACHE.clear)

    def test_local_protected_read_and_both_engine_inventories(self):
        info=inventory();seen=[]
        def get(url,headers=None,timeout=None):
            seen.append((url,headers))
            if '/api/v2/jobs?' in url:
                self.assertEqual(headers,{'Authorization':'Bearer private-probe-value'});return {'jobs':[]}
            if url.endswith('/api/v2/health'):return {'status':'healthy','upstream':'http://127.0.0.1:8188'}
            if '/object_info/' in url:
                from urllib.parse import unquote
                name=unquote(url.rsplit('/',1)[1]);return {name:info[name]}
            raise AssertionError(url)
        with patch.object(readiness,'_json_get',side_effect=get),patch.object(compute_probe.shutil,'which',return_value='/bin/tool'):
            report=compute_probe.diagnose_target(Target('http://127.0.0.1:8189','private-probe-value'))
        self.assertTrue(report['connected']);self.assertTrue(report['ready'],report)
        self.assertEqual({e['status'] for e in report['engines'].values()},{'ready'})
        self.assertNotIn('private-probe-value',json.dumps(report))
        self.assertFalse(any('/assets' in url or '/prompt' in url for url,_ in seen))

    def test_remote_auth_success_is_unknown_not_false_missing_or_ready(self):
        with patch.object(readiness,'_json_get',return_value={'jobs':[]}) as get:
            report=compute_probe.diagnose_target(Target('https://example.run.comfy.app','private-probe-value'))
        self.assertTrue(report['connected']);self.assertFalse(report['ready'])
        self.assertEqual({e['status'] for e in report['engines'].values()},{'unknown'})
        get.assert_called_once()
        for engine in report['engines'].values():self.assertFalse(engine['missing_nodes'])

    def test_cloud_uses_its_inventory_not_unsupported_job_listing(self):
        with patch.object(readiness,'_json_get',return_value=inventory()) as get,patch.object(compute_probe.shutil,'which',return_value='/bin/tool'):
            report=compute_probe.diagnose_target(Target('https://cloud.comfy.org','private-probe-value'))
        self.assertTrue(report['ready'],report)
        get.assert_called_once()
        self.assertTrue(get.call_args.args[0].endswith('/api/object_info'))
        self.assertEqual(get.call_args.args[1],{'X-API-Key':'private-probe-value'})

    def test_missing_key_auth_failure_and_missing_nodes_are_distinct(self):
        with patch.object(readiness,'_json_get') as get:
            report=compute_probe.diagnose_target(Target('https://cloud.comfy.org'))
            self.assertFalse(report['connected']);get.assert_not_called()
        with patch.object(readiness,'_json_get',side_effect=HTTPError('https://example',401,'private-probe-value',{},None)):
            report=compute_probe.diagnose_target(Target('https://example.run.comfy.app','private-probe-value'))
            self.assertFalse(report['connected']);self.assertIn('Authentication',report['issues'][0])
            self.assertNotIn('private-probe-value',json.dumps(report))
        with patch.object(readiness,'_json_get',return_value={}),patch.object(compute_probe.shutil,'which',return_value='/bin/tool'):
            report=compute_probe.diagnose_target(Target('https://cloud.comfy.org','private-probe-value'))
            self.assertTrue(report['connected']);self.assertFalse(report['ready'])
            self.assertEqual(report['engines']['h3']['status'],'missing')

    def test_deadline_restores_context_and_prevents_network_after_expiry(self):
        with patch.object(readiness.time,'monotonic',side_effect=[100,121]),patch.object(readiness,'urlopen') as get:
            report=compute_probe.diagnose_target(Target('http://127.0.0.1:8189'))
        get.assert_not_called();self.assertFalse(report['connected'])
        self.assertIsNone(readiness._READ_DEADLINE.get())

    def test_credential_metadata_requests_do_not_follow_redirects(self):
        redirect=readiness._NoCredentialRedirect()
        self.assertIsNone(redirect.redirect_request(None,None,302,'redirect',{},'https://elsewhere.example'))


if __name__=='__main__':unittest.main()
