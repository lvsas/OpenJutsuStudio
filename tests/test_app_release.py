"""Pre-release identity is shared; format versions and engine maturity remain distinct."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


class AppReleaseTests(unittest.TestCase):
    def test_one_prerelease_version_and_fallback_markup(self):
        from app_release import VERSION, render_release
        self.assertRegex(VERSION, r'^0\.\d+\.\d+-alpha\.\d+$')
        for name in ('index', 'h3', 'character', 'timeline'):
            with self.subTest(page=name):
                raw = (ROOT / 'src/templates' / (name + '.html')).read_text()
                self.assertEqual(raw.count('href="/static/studio-wip.css"'), 1,
                                 'Every WIP notice must load the same shared stylesheet')
                self.assertLess(raw.index('/static/app.css'), raw.index('/static/studio-wip.css'))
                self.assertEqual(raw.count('class="studio-wip"'), 1)
                self.assertIn('<strong>Work in progress</strong>', raw)
                self.assertEqual(raw.count('<span data-app-version>v0 alpha</span>'), 1)
                rendered = render_release(raw)
                self.assertIn(f'<span data-app-version>v{VERSION}</span>', rendered)
                self.assertEqual(render_release(rendered), rendered)
        self.assertEqual(render_release('plain HTML'), 'plain HTML')
        self.assertIn(f'v{VERSION}', (ROOT / 'README.md').read_text())

    def test_served_pages_and_openapi_match_in_an_isolated_workspace(self):
        code = '''import json,sys
from pathlib import Path
import core
core.WORK=Path(sys.argv[1])
import app
from app_release import VERSION
from fastapi.testclient import TestClient
with TestClient(app.app) as client:
    assert client.get('/openapi.json').json()['info']['version']==VERSION
    for path in ('/','/h3','/characters','/timeline'):
        r=client.get(path)
        assert r.status_code==200,(path,r.status_code)
        assert '<span data-app-version>v'+VERSION+'</span>' in r.text,path
        assert r.text.count('href="/static/studio-wip.css"')==1,path
        assert 'v0 alpha</span>' not in r.text,path
    assert client.get('/static/studio-wip.css').status_code==200
print(json.dumps({'ok':True}))
'''
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'),
                   OPENGENJUTSU_H3_STUDIO_ENABLED='1', OPENGENJUTSU_CHARACTER_STUDIO_ENABLED='1')
        with tempfile.TemporaryDirectory() as work:
            result = subprocess.run([sys.executable, '-c', code, work], cwd=ROOT,
                                    env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])


if __name__ == '__main__':
    unittest.main()
