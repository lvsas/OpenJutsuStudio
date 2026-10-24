import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as module

class AssemblyPageTests(TestCase):
    def test_retired_editor_redirects_to_sequence_without_serving_legacy_ui(self):
        client=TestClient(module.app)
        native=client.get('/timeline')
        self.assertEqual(native.status_code,200)
        for value in ('supporting-tools','Assemble selected results','id="clip-editor"',
                      'Open archived cut','sequence-toolbar','src="/static/timeline.js"'):
            self.assertNotIn(value,native.text)
        self.assertIn('id="native-video"',native.text)
        self.assertEqual(native.text.count('id="timeline-export-dialog"'),1)
        self.assertEqual(native.text.count('id="download-export"'),1)
        self.assertNotIn('<!-- shared-export-dialog -->',native.text)
        with TemporaryDirectory() as root, patch.object(module.core,'WORK',Path(root)):
            for query,expected in [('', '/timeline'),
                    ('?project_id='+'a'*32+'&job_id='+'b'*32, '/timeline?project_id='+'a'*32)]:
                response=client.get('/assembly'+query,follow_redirects=False)
                self.assertEqual(response.status_code,308)
                self.assertEqual(response.headers['location'],expected)
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_retired_editor_rejects_malformed_or_duplicate_project_without_io(self):
        client=TestClient(module.app)
        with TemporaryDirectory() as root, patch.object(module.core,'WORK',Path(root)):
            for query in ('?project_id=bad','?project_id='+'a'*32+'&project_id='+'b'*32):
                self.assertEqual(client.get('/assembly'+query,follow_redirects=False).status_code,400)
            self.assertEqual(list(Path(root).iterdir()),[])

    def test_fragment_change_invalidates_the_native_page(self):
        with TemporaryDirectory() as root:
            root=Path(root)
            for name in ('timeline.html',):
                (root/name).write_text('<main><!-- shared-export-dialog --></main>')
            fragment=root/'export-dialog.html';fragment.write_text('first')
            with patch.object(module,'TEMPLATES',root),patch.dict(module._PAGE_CACHE,clear=True):
                self.assertIn('first',module._page('timeline.html'))
                stamp=fragment.stat().st_mtime_ns;fragment.write_text('second')
                os.utime(fragment,ns=(stamp+1000,stamp+1000))
                for name in ('timeline.html',):
                    self.assertIn('second',module._page(name))
