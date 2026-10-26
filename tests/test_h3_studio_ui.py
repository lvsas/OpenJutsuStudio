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
        # Both shared helpers are the single implementation used by both studios.
        self.assertEqual([s.get('src') for s in scripts],
                         ['/static/project-session.js', '/static/settings.js', '/static/studio-utils.js', '/static/studio-progress.js', '/static/share-reel.js', '/static/h3-studio.js', '/static/project-context-ui.js'])
        self.assertEqual([s.get('type') for s in scripts], [None, None, None, None, None, 'module', 'module'])
        links = [attrs.get('href') for tag, attrs in self.parser.tags if tag == 'link']
        self.assertEqual(links, ['/static/design-system.css', '/static/app.css', '/static/h3-studio.css', '/static/studio-wip.css', '/static/source-clip.css', '/static/completion.css', '/static/share-reel.css', '/static/project-session.css', '/static/settings.css'])
        for src in self.scripts.values():
            self.assertNotRegex(src, r'innerHTML|outerHTML|insertAdjacentHTML|eval\(|https?://')
        # H3 must not borrow the LTX pipeline's vocabulary. The progress bar is now a
        # shared, honest component fed by the worker's own progress, so it is allowed.
        # Multi-reference is now a real H3 capability, so its field name is allowed.
        self.assertNotRegex(self.html, r'FLUX|Ripple|1024|576|56 frames')
        anchors = [attrs for tag, attrs in self.parser.tags if tag == 'a']
        self.assertTrue(any(a.get('href') == '/h3' and a.get('aria-current') == 'page' for a in anchors))
        self.assertTrue(any(a.get('href') == '/' for a in anchors))
        self.assertIn('territorial and commercial terms', self.html)
        self.assertIn('https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/LICENSE', self.html)
        self.assertIn('does not override', self.html)

    def test_source_and_exactly_one_reference_are_required(self):
        for id_, name in [('h3-video', 'video'), ('h3-reference', 'reference_images')]:
            tag, attrs = self.ids[id_]
            self.assertEqual((tag, attrs['type'], attrs['name']), ('input', 'file', name))
            self.assertIn('required', attrs)
            self.assertNotIn('multiple', attrs)
        # A second reference is optional and off until the operator asks for it.
        second = self.ids['h3-reference-2'][1]
        self.assertEqual(second['name'], 'reference_images')
        self.assertIn('disabled', second)
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
        self.assertIn('report.ready === true', self.scripts['h3-studio.js'])
        self.assertIn('report.warnings', self.scripts['h3-studio.js'])
        self.assertIn('epoch !== this.epoch', take)
        self.assertIn('pixel-identical output is not guaranteed', self.html)
        for id_ in ['h3-result-actions', 'h3-capsule-details']:
            self.assertIn('hidden', self.ids[id_][1])

    def test_readiness_stays_advisory_and_never_blocks_a_valid_input(self):
        main = self.scripts['h3-studio.js']
        # The submit button depends on inputs alone; a false-negative readiness must not lock it.
        self.assertIn("byId('submit').disabled = locked || !inputs || !clip.valid;", main)
        self.assertNotIn("byId('submit').disabled = locked || !ready", main)
        # No client-side preflight: the server is the authoritative gate.
        self.assertNotIn("if (!await checkReadiness()) throw", main)
        self.assertIn('byId(\'run-overlay\').hidden = false;', main)
        # The precise server refusal reason must reach the user.
        self.assertIn('HTTP ${response.status}: ${detail}', self.scripts['h3-http.js'])

    def test_shared_brand_heading_matches_the_ltx_studio(self):
        ltx = (ROOT / 'src' / 'templates' / 'index.html').read_text()
        for shared in ('<p class="eyebrow">Open video transformation</p>',
                       'Make the swap.<br><em>Keep the moment.</em>'):
            self.assertIn(shared, self.html)
            self.assertIn(shared, ltx)
        # The supporting sentence is engine-specific and must name the real H3 stack.
        self.assertIn('MiniMax H3', self.html)
        self.assertIn('Character Swap LoRA', self.html)
        self.assertNotIn('FLUX', self.html)

    def test_shared_interface_markers_match_the_ltx_studio(self):
        ltx = (ROOT / 'src' / 'templates' / 'index.html').read_text()
        # Everything the two studios must present identically. Only the accent token
        # and the real engine steps are allowed to differ.
        for marker in ['class="media-picker', 'class="picker-icon" aria-hidden="true"', 'class="picker-drop-hint"',
                       'data-drop-kind=', 'class="reference-thumb"', '<p class="eyebrow">Preview</p>',
                       'class="stage-frame"', 'class="stage-empty"', 'class="stage-video"', 'class="take-story"',
                       'take-stage-card', 'class="run-overlay"', 'class="run-orb"', 'class="progress-track"',
                       'class="run-progress"', 'class="toast-region"', 'class="sr-status"', 'class="export-actions"',
                       'Download result', 'Preview share reel', 'Copy caption',
                       'Add a clear character image', 'class="source-summary"',
                       'class="quality-card selected"', 'class="quality-state"', 'Quality',
                       'class="badge live">ComfyUI inference', 'No public link is created in local mode']:
            self.assertIn(marker, self.html)
            self.assertIn(marker, ltx)
        self.assertIn('Choose a video', self.html)
        # LTX's stage contract: media are direct frame children driven by one state,
        # and the capsule appears with the take. No wrapper panes, no second switcher.
        for absent in ('h3-preview-switch', 'h3-pane-', 'h3-show-source', 'h3-show-reference',
                       'h3-show-result', 'h3-run"', 'class="h3-run '):
            self.assertNotIn(absent, self.html)
        for removed in ('h3-stage', 'h3-timer'):
            self.assertNotIn(removed, self.ids)
        for stage in ('source', 'reference', 'result'):
            self.assertIn(f'id="h3-{stage}-preview"', self.html)
            self.assertIn(f'data-h3-stage="{stage}"', self.html)
        self.assertIn('id="h3-stage-empty"', self.html)
        for id_ in ('h3-take-story', 'h3-run-overlay', 'h3-remove-reference'): self.assertIn('hidden', self.ids[id_][1])
        self.assertEqual(self.ids['h3-run-overlay'][1].get('class'), 'run-overlay')
        self.assertEqual(self.ids['h3-readiness'][1].get('class'), 'badge')
        for gone in ('h3-retry', 'h3-readiness-notes'): self.assertNotIn(gone, self.ids)
        for page in (self.html, ltx): self.assertIn('<span>Generate swap</span>', page)
        for picker, kind, target in [('h3-video-picker', 'video', 'h3-video'),
                                     ('h3-reference-picker', 'image', 'h3-reference')]:
            self.assertEqual((kind, target), (self.ids[picker][1]['data-drop-kind'], self.ids[picker][1]['for']))

    def test_shared_components_are_the_only_implementations(self):
        main, take, http = (self.scripts[name] for name in ('h3-studio.js', 'h3-take.js', 'h3-http.js'))
        for control in ('h3-download', 'h3-build-reel', 'h3-copy-caption', 'h3-save-capsule', 'h3-replay'): self.assertIn(control, self.ids)
        self.assertIn('disabled', self.ids['h3-build-reel'][1])
        self.assertNotIn('disabled', self.ids['h3-copy-caption'][1])
        for marker in ('bindFileDropTargets', 'replaceChildren', "byId('remove-reference')"): self.assertIn(marker, main)
        for marker in ("renderProgress?.(job, 'h3-')", "byId('take-story').hidden = false",
                       "this.onStage?.('result')", "byId('build-reel').disabled = false"):
            self.assertIn(marker, take)
        for marker in ('export function setStage(mode)', "byId('stage-empty').hidden",
                       'export function loadStageMedia(kind, url)', '/reveal'): self.assertIn(marker, http)
        for gone in ('showMedia', 'description'):
            self.assertNotIn(gone, http)
        for gone in ('display: contents', 'file-selector-button', 'h3-run '): self.assertNotIn(gone, (STATIC / 'h3-studio.css').read_text())
        progress = (STATIC / 'studio-progress.js').read_text()
        self.assertIn("'minimax-h3'", progress)
        self.assertIn("prefix = ''", progress)
        self.assertEqual('visually-hidden', self.ids['h3-video'][1]['class'])
        # The caption describes the result, not the implementation stack.
        captions = [line for line in take.splitlines() if 'Made with OpenGenjutsu' in line]
        self.assertEqual(len(captions), 1)
        self.assertIn('Same moment. New character.', captions[0])
        self.assertNotIn('LTX', captions[0])

    def test_character_description_is_user_owned_and_reaches_the_payload(self):
        tag, attrs = self.ids['h3-description']
        self.assertEqual((tag, attrs['name']), ('input', 'character_description'))
        self.assertEqual(attrs['maxlength'], '2000')
        self.assertNotIn('required', attrs)
        # It shares the Optional directions disclosure, so the visible panel matches LTX.
        self.assertLess(self.html.index('class="advanced-settings directions-step"'),
                        self.html.index('id="h3-description"'))
        main = self.scripts['h3-studio.js']
        self.assertIn("data.delete('character_description')", main)
        self.assertIn("for (const field of ['edit', 'description'])", main)
        # The description is client-supplied text, never generated in the transport layer.
        self.assertNotIn('description', self.scripts['h3-http.js'])

    def test_scoped_theme_and_small_modules(self):
        css = (STATIC / 'h3-studio.css').read_text()
        for marker in ('html[data-engine="h3"]', '--accent: #ff4f2e', 'prefers-reduced-motion'):
            self.assertIn(marker, css)
        for path in [HTML, STATIC / 'h3-studio.css', *(STATIC / name for name in MODULES), Path(__file__), ROOT / 'tests/h3_studio_contract.mjs']:
            self.assertLessEqual(len(path.read_text().splitlines()), 300 if path.suffix in ('.js', '.mjs') else 220, str(path))
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