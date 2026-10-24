import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fastapi.testclient import TestClient
core = importlib.import_module("core")
studio = importlib.import_module("app")


class TimelineRegistrationTests(unittest.TestCase):
    def test_app_serves_editor_and_persists_revisioned_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / 'media'
            media.mkdir()
            with patch.object(core, 'WORK', root), patch.object(studio, 'MEDIA_DIR', media):
                with TestClient(studio.app) as client:
                    page = client.get('/timeline')
                    self.assertEqual(page.status_code, 200)
                    self.assertNotIn('id="clip-track"', page.text)
                    retired = client.get('/assembly', follow_redirects=False)
                    self.assertEqual(retired.status_code, 308)
                    self.assertEqual(retired.headers['location'], '/timeline')
                    self.assertIn('Work in progress', page.text)
                    self.assertIn('id="native-video"', page.text)
                    native = client.get('/api/continuity/takes')
                    self.assertEqual(native.status_code, 200, native.text)
                    self.assertEqual(native.json(), {'takes': []})
                    self.assertFalse((root / 'timeline' / 'continuable-takes').exists())
                    created = client.post('/api/timeline/projects', json={'title': 'My verified cut'})
                    self.assertEqual(created.status_code, 201, created.text)
                    project = created.json()
                    target = f'/api/timeline/projects/{project["project_id"]}'
                    self.assertEqual(client.get(target).json(), project)
                    saved = client.patch(target, json={'revision': project['revision'],
                                                       'title': 'Renamed cut', 'clips': []})
                    self.assertEqual(saved.status_code, 200, saved.text)
                    self.assertEqual(client.get(target).json()['title'], 'Renamed cut')
                    stale = client.patch(target, json={'revision': project['revision'], 'clips': []})
                    self.assertEqual(stale.status_code, 409)
                    self.assertEqual(client.get('/api/characters/library').status_code, 200)
