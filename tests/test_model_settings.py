"""Model aliases are target-scoped, explicit and immutable for each snapshot."""
import json
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from compute_settings import Store, SettingsError
import test_compute_settings as settings_fixtures


class ModelSettingsTests(unittest.TestCase):
    setUp = settings_fixtures.SettingsTests.setUp

    def test_save_read_and_immutable_snapshot(self):
        aliases = {'ltx_unet': 'renamed/My LTX.safetensors'}
        first = self.store.save(0, 'http://localhost:9010', model_bindings=aliases)
        aliases['ltx_unet'] = 'changed.safetensors'
        self.assertEqual(first.model_bindings['ltx_unet'], 'renamed/My LTX.safetensors')
        with self.assertRaises(TypeError):
            first.model_bindings['ltx_unet'] = 'changed.safetensors'
        self.assertEqual(Store(self.root).current().public()['model_bindings'], dict(first.model_bindings))
        self.store.save(1, first.base_url, model_bindings={'ltx_unet': 'second.safetensors'})
        self.assertEqual(first.model_bindings['ltx_unet'], 'renamed/My LTX.safetensors')

    def test_target_scoping_and_explicit_reset(self):
        self.store.save(0, 'http://localhost:9010', api_key='private-test', model_bindings={'h3_unet':'H3/renamed.safetensors'})
        self.assertEqual(self.store.candidate('http://localhost:9010').model_bindings['h3_unet'], 'H3/renamed.safetensors')
        changed = self.store.candidate('https://other.example')
        self.assertEqual(dict(changed.model_bindings), {})
        self.assertEqual(changed.api_key, '')
        self.assertEqual(dict(self.store.candidate('http://localhost:9010', model_bindings={}).model_bindings), {})
        self.store.save(1, 'http://localhost:9010', clear=True)
        self.assertIn('h3_unet', self.store.current().model_bindings)

    def test_legacy_record_reads_without_write_or_profile_reinterpretation(self):
        self.store.save(0, 'http://localhost:9010')
        self.store.path.write_text(json.dumps({'revision':1,'base_url':'http://localhost:9010','api_key':''}))
        before = self.store.path.read_bytes()
        self.assertEqual(dict(self.store.current().model_bindings), {})
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_invalid_roles_and_paths_never_echo_or_persist(self):
        for bad in ({'private-test':'model.safetensors'}, {'ltx_unet':'../private-test'},
                    {'ltx_unet':'/private-test/model'}, {'ltx_unet':False}, []):
            with self.subTest(bad=bad), self.assertRaises(SettingsError) as raised:
                self.store.candidate('http://localhost:9010', model_bindings=bad)
            self.assertNotIn('private-test', str(raised.exception))
            self.assertFalse(self.store.path.exists())

    def test_revision_conflict_wins_before_validating_new_bindings(self):
        self.store.save(0, 'http://localhost:9010', model_bindings={'h3_clip':'encoder.safetensors'})
        before = self.store.path.read_bytes()
        with self.assertRaises(SettingsError) as raised:
            self.store.save(0, 'http://localhost:9010', model_bindings={'bad':'private-test'})
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.store.path.read_bytes(), before)
