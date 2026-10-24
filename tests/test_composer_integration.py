"""Frozen references and read-only native capability selection; no GPU fixtures."""
import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import continuity_attempts as attempts
from continuity_composer import operation_options
from types import SimpleNamespace

class ComposerIntegrationTests(unittest.TestCase):
    def test_reference_snapshot_survives_callback_mutation_and_idempotent_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            kwargs=dict(take_id='a'*32,prompt='Continue',raw_frames=158,seeds=[7,8],request_id='b'*32)
            record,_=attempts.create_or_get(root,**kwargs,frozen_reference_paths=['/synthetic/original.png'])
            seen=[]
            def refine(prompt,take_id,**context):
                self.assertEqual(context['reference_paths'],['/synthetic/original.png'])
                context['reference_paths'].append('/synthetic/unwanted.png')
                return 'Prepared'
            def submit(op,prompt,seed,raw,take,**context):
                seen.append(context['reference_paths']);return op
            result=attempts.run(root,record['attempt_id'],refine=refine,submit=submit)
            self.assertEqual(result['status'],'done')
            self.assertEqual(seen,[['/synthetic/original.png'],['/synthetic/original.png']])
            again,created=attempts.create_or_get(root,**kwargs,frozen_reference_paths=['/synthetic/new-draft.png'])
            self.assertFalse(created)
            self.assertEqual(again['frozen_reference_paths'],['/synthetic/original.png'])
            self.assertNotIn('/synthetic/',str(attempts.public(again)))

    def test_root_options_and_anchor_refusals_are_read_only(self):
        options=operation_options('/synthetic-work','root')
        self.assertTrue(options['available'])
        self.assertTrue(all(o['seconds']>0 for o in options['duration_options']))
        with self.assertRaises(ValueError):operation_options('/synthetic-work','bridge','a'*32,'a'*32)

    def test_graph_inventory_queries_only_consumed_classes(self):
        import readiness
        graph={'one':{'class_type':'Only This Node','inputs':{}}}
        def get(url,*args,**kwargs):
            if url.endswith('/api/v2/health'):return {'status':'healthy','upstream':'http://upstream.invalid'}
            raise AssertionError(url)
        with patch('readiness.comfy_base_url',return_value='http://127.0.0.1:8189'),patch(
                'readiness._json_get',side_effect=get),patch('readiness._object_info',return_value={
                'Only This Node':{'input':{'required':{}}}}) as node:
            self.assertEqual(readiness.missing_dependencies(graph),([],[]))
            self.assertEqual(node.call_args.args[0],'http://upstream.invalid/object_info/Only%20This%20Node')

    def test_dynamic_reference_capacity_uses_installed_schema(self):
        import readiness
        info={'Dynamic':{'input':{'optional':{'refs':['COMFY_AUTOGROW_V3',{'template':{
            'prefix':'image_','max':2}}]}}}}
        with self.assertRaises(ValueError):
            readiness._inventory(info,{'node':{'class_type':'Dynamic','inputs':{'refs.image_2':['image',0]}}})

    def test_missing_timing_refuses_before_any_length_is_offered(self):
        family=SimpleNamespace(artifacts=SimpleNamespace(to_manifest=lambda:{'context':
            {'width':1280,'height':704,'fps':24,'self_id':'native-a'}}))
        with patch('continuity_composer.get_validated_family',return_value=family),patch(
                'continuity_composer.state_from_family',return_value=None):
            with self.assertRaises(ValueError):operation_options('/synthetic-work','prepend','a'*32)
