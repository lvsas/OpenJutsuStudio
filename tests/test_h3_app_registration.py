"""H3 page/API register by default and can be explicitly disabled."""
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import h3_studio_app


class H3AppRegistrationTests(unittest.TestCase):
    def test_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
                h3_studio_app, '_h3_readiness', return_value={
                    'ready': True, 'issues': [], 'warnings': []}):
            app = FastAPI()
            with ThreadPoolExecutor(max_workers=1) as executor:
                self.assertTrue(h3_studio_app.register_optional_h3(app, executor, lambda: Path('.'), 1024))
                with TestClient(app) as client:
                    self.assertEqual(client.get('/h3').status_code, 200)
                    self.assertTrue(client.get('/api/h3/readiness').json()['ready'])

    def test_can_be_explicitly_disabled(self):
        with patch.dict(os.environ, {'OPENGENJUTSU_H3_STUDIO_ENABLED': '0'}, clear=True):
            app = FastAPI()
            with ThreadPoolExecutor(max_workers=1) as executor:
                self.assertFalse(h3_studio_app.register_optional_h3(app, executor, lambda: Path('.'), 1024))
                with TestClient(app) as client:
                    self.assertEqual(client.get('/h3').status_code, 404)
                    self.assertEqual(client.get('/api/h3/readiness').status_code, 404)

    def test_enabled_registration_exposes_page_and_h3_readiness_only(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, {'OPENGENJUTSU_H3_STUDIO_ENABLED': 'true'}, clear=True), \
                patch.object(h3_studio_app, '_h3_readiness', return_value={
                    'ready': False, 'issues': ['H3 weights missing'], 'warnings': []}):
            app = FastAPI()
            with ThreadPoolExecutor(max_workers=1) as executor:
                self.assertTrue(h3_studio_app.register_optional_h3(
                    app, executor, lambda: Path(tmp), 1024))
                with TestClient(app) as client:
                    page = client.get('/h3')
                    self.assertEqual(page.status_code, 200)
                    self.assertIn('H3 Studio', page.text)
                    self.assertIn('data-engine="h3"', page.text)
                    report = client.get('/api/h3/readiness')
                    self.assertEqual(report.status_code, 200)
                    self.assertEqual(report.json()['issues'], ['H3 weights missing'])
                    self.assertEqual(client.get('/api/h3/jobs/not-a-valid-id/reference').status_code, 404)


if __name__ == '__main__':
    unittest.main()
