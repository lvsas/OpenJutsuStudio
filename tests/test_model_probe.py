"""The diagnostic checks its draft target, not ambient or historical settings."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import compute_probe
import readiness
from compute_settings import Target
from test_compute_probe import inventory


class ModelProbeTests(unittest.TestCase):
    def test_draft_aliases_and_exact_loader_choices(self):
        info = inventory()
        renamed = 'different-folder/H3 CASE.safetensors'
        info['UNETLoader']['input']['required']['unet_name'] = ['COMBO', {'options': [renamed]}]
        target = Target('https://cloud.comfy.org', 'private-test', model_bindings={'h3_unet': renamed})
        with patch.object(readiness, '_json_get', return_value=info), patch.object(compute_probe.shutil, 'which', return_value='/bin/tool'):
            report = compute_probe.diagnose_target(target)
        self.assertEqual(report['engines']['h3']['status'], 'ready', report)
        self.assertEqual(report['model_inventory']['choices']['h3_unet'], [renamed])
        self.assertNotIn(renamed, report['engines']['h3']['missing_models'])
        self.assertEqual(report['engines']['ltx']['status'], 'missing')

    def test_remote_without_inventory_never_suggests_defaults_as_discovered_files(self):
        with patch.object(readiness, '_json_get', return_value={'jobs': []}):
            report = compute_probe.diagnose_target(Target('https://example.run.comfy.app', 'private-test'))
        self.assertEqual(report['model_inventory'], {'status': 'unknown', 'choices': {}})

    def test_every_supported_combo_shape_is_honored_and_unknown_is_not_empty(self):
        field = 'renamed.safetensors'
        for spec in ([[field]], [[field], {}], ['COMBO', {'options': [field]}], [{'options':[field]}, {}]):
            with self.subTest(spec=spec):
                info={'UNETLoader': {'input': {'required': {'unet_name':spec}}}}
                self.assertEqual(readiness._inventory(info, {'1': {'class_type':'UNETLoader', 'inputs':{'unet_name':field}}}), ([], []))
        with self.assertRaises(ValueError):
            readiness._inventory({'UNETLoader':{'input':{'required':{'unet_name':['STRING', {}]}}}}, {'1': {'class_type':'UNETLoader','inputs':{'unet_name':field}}})
