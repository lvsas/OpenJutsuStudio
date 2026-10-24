import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as module

class AssemblyPageTests(TestCase):
    def test_views_have_exclusive_editors_and_one_shared_export(self):
        client=TestClient(module.app)
        native=client.get('/timeline');legacy=client.get('/assembly')
        self.assertEqual(native.status_code,200);self.assertEqual(legacy.status_code,200)
        for value in ('supporting-tools','Assemble selected results','Optional · after choosing your results','id="clip-editor"'):
            self.assertNotIn(value,native.text)
        self.assertNotIn('Saved cuts &amp; MP4 tools',native.text)
        self.assertIn('Open archived cut',native.text)
        self.assertIn('id="native-video"',native.text)
        for value in ('id="timeline-video"','id="clip-editor"','id="import-file"','src="/static/timeline.js"'):
            self.assertIn(value,legacy.text)
        self.assertNotIn('id="native-video"',legacy.text)
        self.assertNotIn('/static/continuity-studio.js',legacy.text)
        for page in (native.text,legacy.text):
            self.assertEqual(page.count('id="timeline-export-dialog"'),1)
            self.assertEqual(page.count('id="download-export"'),1)
            self.assertNotIn('<!-- shared-export-dialog -->',page)

    def test_fragment_change_invalidates_both_cached_pages(self):
        with TemporaryDirectory() as root:
            root=Path(root)
            for name in ('timeline.html','assembly.html'):
                (root/name).write_text('<main><!-- shared-export-dialog --></main>')
            fragment=root/'export-dialog.html';fragment.write_text('first')
            with patch.object(module,'TEMPLATES',root),patch.dict(module._PAGE_CACHE,clear=True):
                self.assertIn('first',module._page('timeline.html'))
                self.assertIn('first',module._page('assembly.html'))
                stamp=fragment.stat().st_mtime_ns;fragment.write_text('second')
                os.utime(fragment,ns=(stamp+1000,stamp+1000))
                for name in ('timeline.html','assembly.html'):
                    self.assertIn('second',module._page(name))
