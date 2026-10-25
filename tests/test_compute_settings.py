"""Private compute settings and isolated SDK construction, no network/GPU."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from compute_settings import Store, SettingsError


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'new-work'
        self.store = Store(self.root)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)

    def test_read_is_local_default_and_creates_nothing(self):
        current = self.store.current()
        self.assertEqual(current.base_url, 'http://127.0.0.1:8189')
        self.assertEqual(current.public()['source'], 'default')
        self.assertFalse(self.root.exists())
        os.environ['COMFY_BASE_URL'] = 'https://cloud.comfy.org'
        self.assertEqual(self.store.current().base_url, current.base_url)

    def test_save_restart_redaction_and_permissions(self):
        chosen = self.store.save(0, 'https://example.run.comfy.app/', api_key='private-test-value')
        self.assertEqual(chosen.revision, 1)
        self.assertEqual(Store(self.root).current(), chosen)
        self.assertNotIn('private-test-value', repr(chosen))
        self.assertNotIn('private-test-value', json.dumps(chosen.public()))
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.store.path.parent.stat().st_mode), 0o700)

    def test_revision_conflict_never_overwrites(self):
        self.store.save(0, 'http://localhost:9000')
        with self.assertRaises(SettingsError) as error:
            self.store.save(0, 'http://localhost:9001')
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.store.current().revision, 1)

    def test_credential_is_bound_to_unchanged_url(self):
        self.store.save(0, 'https://example.run.comfy.app', api_key='private-test-value')
        self.assertEqual(self.store.candidate('https://example.run.comfy.app').api_key, 'private-test-value')
        self.assertEqual(self.store.candidate('https://elsewhere.example').api_key, '')
        self.assertEqual(self.store.candidate('https://example.run.comfy.app', clear=True).api_key, '')
        self.store.save(1, 'https://example.run.comfy.app', clear=True)
        self.assertFalse(self.store.current().public()['api_key_configured'])

    def test_invalid_input_or_corrupt_store_is_not_defaulted(self):
        for url in ('file:///etc/passwd', 'http://key:secret@host', 'https://host/?key=secret', '', 'http://host/#secret'):
            with self.subTest(url=url), self.assertRaises(SettingsError):
                self.store.candidate(url)
        self.store.save(0, 'http://localhost:9000')
        self.store.path.write_text('{broken')
        with self.assertRaises(SettingsError):
            self.store.current()

    def test_sdk_uses_snapshot_and_restores_ambient_credentials(self):
        import config
        import comfy_transport
        from compute_settings import sdk_environment
        first = self.store.save(0, 'http://localhost:9010', api_key='first-secret')
        os.environ['COMFY_API_KEY'] = 'ambient-secret'
        os.environ['COMFY_BASE_URL'] = 'https://ambient.example'
        with patch.object(config, 'compute_target', return_value=first):
            client = comfy_transport.make_client()
        self.addCleanup(client.close)
        self.assertEqual(client._low.safe_base_url, first.base_url)
        self.store.save(1, 'http://localhost:9020', clear=True)
        self.assertEqual(client._low.safe_base_url, first.base_url)
        self.assertEqual(os.environ['COMFY_API_KEY'], 'ambient-secret')
        with sdk_environment(self.store.current()):
            self.assertNotIn('COMFY_API_KEY', os.environ)
        self.assertEqual(os.environ['COMFY_API_KEY'], 'ambient-secret')


if __name__ == '__main__': unittest.main()
