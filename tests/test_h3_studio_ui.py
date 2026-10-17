"""Static isolation checks plus a dependency-free Node contract harness (no GPU)."""
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'src' / 'static'
HTML = ROOT / 'src' / 'templates' / 'h3.html'
MODULES = ['h3-http.js', 'h3-take.js', 'h3-studio.js']


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class H3StudioUITests(unittest.TestCase):
    def setUp(self):
        self.html = HTML.read_text()
        self.parser = Elements()
        self.parser.feed(self.html)
        self.ids = {attrs['id']: (tag, attrs) for tag, attrs in self.parser.tags if 'id' in attrs}
        self.scripts = {name: (STATIC / name).read_text() for name in MODULES}

    def test_studio_is_isolated_and_only_local_modules_are_loaded(self):
        self.assertIn(('html', {'lang': 'en', 'data-engine': 'h3'}), self.parser.tags)
        scripts = [attrs for tag, attrs in self.parser.tags if tag == 'script']
        # The shared studio helper is the single drag/drop implementation for both studios.
        self.assertEqual([s.get('src') for s in scripts],
                         ['/static/studio-utils.js', '/static/h3-studio.js'])
        self.assertEqual([s.get('type') for s in scripts], [None, 'module'])
        links = [attrs.get('href') for tag, attrs in self.parser.tags if tag == 'link']
        self.assertEqual(links, ['/static/design-system.css', '/static/app.css', '/static/h3-studio.css'])
        for src in self.scripts.values():
            self.assertNotRegex(src, r'innerHTML|outerHTML|insertAdjacentHTML|eval\(|https?://')
        self.assertNotRegex(self.html, r'FLUX|Ripple|reference_images|progressbar|1024|576|56 frames')
        anchors = [attrs for tag, attrs in self.parser.tags if tag == 'a']
        self.assertTrue(any(a.get('href') == '/h3' and a.get('aria-current') == 'page' for a in anchors))
        self.assertTrue(any(a.get('href') == '/' for a in anchors))
        self.assertIn('territorial and commercial terms', self.html)
        self.assertIn('https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/LICENSE', self.html)
        self.assertIn('does not override', self.html)

    def test_source_and_exactly_one_reference_are_required(self):
        for id_, name in [('h3-video', 'video'), ('h3-reference', 'reference_image')]:
            tag, attrs = self.ids[id_]
            self.assertEqual((tag, attrs['type'], attrs['name']), ('input', 'file', name))
            self.assertIn('required', attrs)
            self.assertNotIn('multiple', attrs)
        self.assertNotIn('open', self.ids['h3-directions'][1])
        self.assertIn('disabled', self.ids['h3-edit'][1])
        main = self.scripts['h3-studio.js']
        self.assertIn("data.delete('edit_prompt')", main)
        self.assertNotIn('.trim(', main)
        self.assertNotRegex(main, r"byId\('edit'\)\.value\s*=")
        self.assertIn('18446744073709551615n', main)

    def test_replay_and_truthful_persistence_contract(self):
        take = self.scripts['h3-take.js']
        for literal in ['opengenjutsu.h3.current-job', 'minimax-h3', "'/replay'", "'/capsule'", "'/reference'", "'/source'", "'/result'"]:
            self.assertIn(literal, take)
        self.assertIn('job.started', take)
        self.assertIn('job.finished', take)
        self.assertIn('job.created', take)
        self.assertNotIn('job.progress', take)
        self.assertIn('report.ready === true', self.scripts['h3-studio.js'])
        self.assertIn('report.warnings', self.scripts['h3-studio.js'])
        self.assertIn('epoch !== this.epoch', take)
        self.assertIn('pixel-identical output is not guaranteed', self.html)
        for id_ in ['h3-result-actions', 'h3-capsule-details']:
            self.assertIn('hidden', self.ids[id_][1])

    def test_readiness_stays_advisory_and_never_blocks_a_valid_input(self):
        main = self.scripts['h3-studio.js']
        # The submit button depends on inputs alone; a false-negative readiness must not lock it.
        self.assertIn("byId('submit').disabled = locked || !inputs;", main)
        self.assertNotIn("byId('submit').disabled = locked || !ready", main)
        # No client-side preflight: the server is the authoritative gate.
        self.assertNotIn("if (!await checkReadiness()) throw", main)
        self.assertIn("byId('status').textContent = 'Uploading inputs.", main)
        # The precise server refusal reason must reach the user.
        self.assertIn('HTTP ${response.status}: ${detail}', self.scripts['h3-http.js'])

    def test_shared_brand_heading_matches_the_ltx_studio(self):
        ltx = (ROOT / 'src' / 'templates' / 'index.html').read_text()
        for shared in ('<p class="eyebrow">Open video transformation</p>',
                       'Make the edit.<br><em>Keep the moment.</em>'):
            self.assertIn(shared, self.html)
            self.assertIn(shared, ltx)
        # The supporting sentence is engine-specific and must name the real H3 stack.
        self.assertIn('MiniMax H3', self.html)
        self.assertIn('Character Swap LoRA', self.html)
        self.assertNotIn('FLUX', self.html)

    def test_media_pickers_match_the_ltx_studio_contract(self):
        ltx = (ROOT / 'src' / 'templates' / 'index.html').read_text()
        # Both studios use the same shared picker markup, icon and drag/drop hook.
        for shared in ['class="media-picker', 'class="picker-icon" aria-hidden="true"', 'class="picker-drop-hint"', 'data-drop-kind=', 'class="reference-thumb"']:
            self.assertIn(shared, self.html)
            self.assertIn(shared, ltx)
        self.assertEqual('visually-hidden', self.ids['h3-video'][1]['class'])
        self.assertEqual('visually-hidden', self.ids['h3-reference'][1]['class'])
        self.assertEqual(('video', 'h3-video'), (self.ids['h3-video-picker'][1]['data-drop-kind'], self.ids['h3-video-picker'][1]['for']))
        self.assertEqual(('image', 'h3-reference'), (self.ids['h3-reference-picker'][1]['data-drop-kind'], self.ids['h3-reference-picker'][1]['for']))
        self.assertIn('hidden', self.ids['h3-remove-reference'][1])
        self.assertIn('Choose one continuous shot', self.html)
        self.assertIn('Add a clear character image', self.html)
        main = self.scripts['h3-studio.js']
        self.assertIn('bindFileDropTargets', main)
        self.assertIn("byId('remove-reference')", main)
        self.assertIn('replaceChildren', main)
        # The raw native file control must no longer be themed as a visible input.
        self.assertNotIn('file-selector-button', (STATIC / 'h3-studio.css').read_text())

    def test_character_description_is_user_owned_and_reaches_the_payload(self):
        tag, attrs = self.ids['h3-description']
        self.assertEqual((tag, attrs['name']), ('input', 'character_description'))
        self.assertEqual(attrs['maxlength'], '2000')
        self.assertNotIn('required', attrs)
        self.assertIn('inserted verbatim', self.html)
        main = self.scripts['h3-studio.js']
        self.assertIn("['video', 'reference', 'description', 'seed']", main)
        # The description is client-supplied text, never generated in the transport layer.
        self.assertNotIn('description', self.scripts['h3-http.js'])

    def test_scoped_theme_and_small_modules(self):
        css = (STATIC / 'h3-studio.css').read_text()
        self.assertIn('html[data-engine="h3"]', css)
        self.assertIn('--accent: #ff4f2e', css)
        self.assertIn('prefers-reduced-motion', css)
        for path in [HTML, STATIC / 'h3-studio.css', *(STATIC / name for name in MODULES), Path(__file__), ROOT / 'tests/h3_studio_contract.mjs']:
            self.assertLessEqual(len(path.read_text().splitlines()), 200, str(path))
        ids = [attrs['id'] for _, attrs in self.parser.tags if 'id' in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        for source in self.scripts.values():
            for id_ in re.findall(r"byId\('([^']+)'\)", source):
                self.assertIn(f'h3-{id_}', self.ids)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for JS contract tests')
    def test_javascript_contract_harness(self):
        result = subprocess.run(['node', '--experimental-default-type=module', 'tests/h3_studio_contract.mjs'],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('H3 UI contract checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
