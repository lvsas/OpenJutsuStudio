"""HTTP contract for target-scoped filename aliases; tests never generate."""
import unittest
import test_compute_settings_api as settings_fixtures
from compute_settings import Store


class ModelSettingsAPITests(unittest.TestCase):
    setUp = settings_fixtures.SettingsAPITests.setUp
    save = settings_fixtures.SettingsAPITests.save

    def test_catalog_roundtrip_and_target_scoping(self):
        data = self.client.get('/api/settings/compute').json()
        self.assertEqual(data['model_bindings'], {})
        keys = [role['key'] for role in data['model_roles']]
        self.assertIn('h3_unet', keys)
        self.assertEqual(len(keys), len(set(keys)))
        aliases = {'ltx_unet':'Renamed/Model With Spaces.safetensors'}
        saved = self.save(model_bindings=aliases)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get('/api/settings/compute').json()['model_bindings'], aliases)
        response = self.client.put('/api/settings/compute', json={'revision':1, 'base_url':'https://new.example'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['model_bindings'], {})
        self.probe.assert_not_called()

    def test_probe_uses_draft_models_and_never_saves_them(self):
        aliases = {'h3_upscaler':'Different Upscaler.safetensors'}
        response = self.client.post('/api/settings/compute/test', json={'base_url':'https://new.example', 'model_bindings':aliases})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(dict(self.probe.call_args.args[0].model_bindings), aliases)
        self.assertFalse(self.root.exists())

    def test_invalid_bindings_are_generic_no_store_and_no_probe(self):
        for aliases in (None, [], {'unknown':'private-invalid-token'}, {'h3_unet':'../private-invalid-token'}):
            for path, method in (('/api/settings/compute', self.client.put), ('/api/settings/compute/test', self.client.post)):
                with self.subTest(aliases=aliases, path=path):
                    payload = {'base_url':'https://new.example', 'model_bindings':aliases}
                    if method == self.client.put:
                        payload['revision'] = 0
                    response = method(path, json=payload)
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertNotIn('private-invalid-token', response.text)
                    self.assertFalse(Store(self.root).path.exists())
        self.probe.assert_not_called()

    def test_alias_only_activation_remains_blocked_by_work(self):
        self.activity.extra_busy = lambda: True
        response = self.save(model_bindings={'flux_clip':'Renamed.safetensors'})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.root.exists())
