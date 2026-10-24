import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def markup_for(name):
    return (ROOT / 'src/templates' / name).read_text().replace('<!-- shared-export-dialog -->', (ROOT / 'src/templates/export-dialog.html').read_text())


def luminance(color):
    parts = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    linear = [part/12.92 if part <= .04045 else ((part+.055)/1.055)**2.4 for part in parts]
    return .2126*linear[0]+.7152*linear[1]+.0722*linear[2]


class TimelineStudioUITests(unittest.TestCase):
    def test_native_take_is_primary_without_a_duplicate_editor(self):
        markup = (ROOT / 'src/templates/timeline.html').read_text()
        script = (ROOT / 'src/static/continuity-studio.js').read_text()
        self.assertIn('Work in progress', markup)
        self.assertIn('id="native-video"', markup)
        self.assertIn('id="native-capsule"', markup)
        self.assertNotIn('supporting-tools', markup)
        self.assertIn('href="/assembly"', markup)
        self.assertNotIn('src="/static/timeline.js"', markup)
        self.assertNotIn("import('./timeline.js')", script)
        self.assertIn("getJSON('/api/continuity/takes')", script)
        self.assertNotIn('innerHTML', script)
        # Generation is supported. The async contract below verifies that only
        # an explicit submit can POST; a whitespace-sensitive no-POST assertion
        # would pass despite real submission code and conceal regressions.
        self.assertNotIn('/api/h3/jobs', script)
        self.assertIn('This public JSON is not a complete Take backup', markup)
        for path in ('timeline.html', 'character.html'):
            page = (ROOT / 'src/templates' / path).read_text()
            self.assertIn('aria-label="Development status"', page)
            self.assertIn('Work in progress', page)
            self.assertIn('/static/studio-wip.css', page)

    @unittest.skipUnless(shutil.which('node'), 'Node required for editor behavior checks')
    def test_state_contract(self):
        result = subprocess.run(['node', '--experimental-default-type=module',
                                 'tests/timeline_ui_contract.mjs'], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required for async editor behavior checks')
    def test_async_contract(self):
        result = subprocess.run(['node', '--experimental-default-type=module',
                                 '--experimental-vm-modules', '--test',
                                 'tests/timeline_async_contract.mjs'], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node required for attempt recovery checks')
    def test_attempt_client_contract(self):
        result = subprocess.run(['node', '--experimental-default-type=module', '--test',
                                 'tests/continuity_attempt_client_contract.mjs'], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_candidate_comparison_has_one_lazy_nonblocking_player(self):
        markup = (ROOT / 'src/templates/timeline.html').read_text()
        script = (ROOT / 'src/static/candidate-comparison.js').read_text()
        css = (ROOT / 'src/static/continuity-studio.css').read_text()
        player_match = re.search(r'<video id="candidate-video"[^>]*>', markup)
        assert player_match is not None, 'Comparison player missing'
        player = player_match.group()
        for attr in ('controls', 'playsinline', 'preload="none"', 'tabindex="0"'):
            self.assertIn(attr, player)
        self.assertNotIn('src=', player)
        self.assertNotIn('autoplay', player)
        self.assertEqual(markup.count('id="candidate-video"'), 1)
        self.assertNotIn('fetch(', script)
        self.assertNotIn('localStorage', script)
        self.assertRegex(css, r'\.candidate\{[^}]*flex-wrap:wrap')
        for selector in ('.candidate .btn', '.candidate-preview .btn'):
            rule_match = re.search(re.escape(selector) + r'\{([^}]+)\}', css)
            assert rule_match is not None, f'Missing rule: {selector}'
            rule = rule_match.group(1)
            self.assertIn('min-height:44px', rule)
            self.assertIn('min-width:44px', rule)
        self.assertRegex(css, r'\.candidate-preview video\{[^}]*width:100%')
        self.assertNotRegex(css, r'\.candidate-preview[^}]*position:\s*(fixed|absolute)')

    def test_editor_shell_keeps_real_controls_and_token_order(self):
        markup = markup_for('assembly.html')
        self.assertLess(markup.index('/static/design-system.css'), markup.index('/static/app.css'))
        self.assertLess(markup.index('/static/app.css'), markup.index('/static/timeline.css'))
        for identifier in ('timeline-video', 'clip-track', 'sequence-seek', 'clip-editor',
                           'trim-start', 'trim-end', 'undo-edit', 'export-sequence',
                           'timeline-export-dialog', 'download-export'):
            self.assertTrue(f'id="{identifier}"' in markup, f'Missing editor control: {identifier}')
        for target in ('/', '/h3', '/characters', '/timeline'):
            self.assertTrue(f'href="{target}"' in markup, f'Missing workspace navigation: {target}')
        self.assertNotRegex(markup.lower(), r'\b(world.first|never.been.done|guaranteed.viral)\b')

    def test_library_exit_and_add_are_not_empty_state_only_controls(self):
        from html.parser import HTMLParser

        class Controls(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack = []
                self.ancestors = {}
                self.attrs = {}

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if attrs.get('id'):
                    self.ancestors[attrs['id']] = [a.get('id') for _, a in self.stack]
                    self.attrs[attrs['id']] = attrs
                if tag not in {'input', 'img', 'meta', 'link', 'br', 'hr'}:
                    self.stack.append((tag, attrs))

            def handle_endtag(self, tag):
                for i in range(len(self.stack)-1, -1, -1):
                    if self.stack[i][0] == tag:
                        del self.stack[i:]
                        break

        page = Controls()
        page.feed((ROOT / 'src/templates/timeline.html').read_text())
        self.assertIn('take-board', page.ancestors['native-rail-add'])
        self.assertNotIn('native-empty', page.ancestors['native-rail-add'])
        self.assertNotIn('hidden', page.attrs['native-rail-add'])
        self.assertIn('native-library', page.ancestors['native-library-close'])
        self.assertNotIn('hidden', page.attrs['forward-reference-input'],
                         'reference picker must remain keyboard focusable')
        self.assertIn('aria-label', page.attrs['forward-reference-input'])

    def test_timeline_has_its_own_legible_accent(self):
        css = (ROOT / 'src/static/timeline.css').read_text()
        accent_match = re.search(r'--accent:\s*(#[0-9a-f]{6})', css)
        ink_match = re.search(r'--accent-ink:\s*(#[0-9a-f]{6})', css)
        if accent_match is None or ink_match is None:
            raise AssertionError('Timeline accent and ink must be explicit')
        accent, ink = accent_match.group(1), ink_match.group(1)
        self.assertEqual(accent, '#bc5cff', 'Timeline owns the vivid ultraviolet identity')
        self.assertEqual(ink, '#210d30')
        self.assertNotIn('200,181,255', css, 'Do not retain pastel states in the ultraviolet ramp')
        for token in ('accent', 'accent-ink', 'accent-soft', 'accent-line', 'accent-card-line',
                      'accent-glow', 'accent-glow-strong', 'accent-light', 'accent-deep'):
            self.assertRegex(css, rf'--{token}:', f'Timeline must override its complete ramp: {token}')
        for foreground, background in ((accent, '#101014'), (ink, accent)):
            light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
            self.assertGreaterEqual((light+.05)/(dark+.05), 4.5)
        self.assertNotIn(accent, ('#d8ff3e', '#22d3ee', '#ff4f2e'))

    def test_editor_does_not_claim_to_generate_native_states(self):
        script = (ROOT / 'src/static/timeline.js').read_text()
        self.assertNotIn('/prompt', script)
        self.assertNotIn('/api/h3/jobs', script)
        self.assertNotIn('innerHTML', script)
        self.assertIn('validateProject', script)
        self.assertIn("method:'PATCH'", script)
        self.assertIn('revision:original.revision', script)
        self.assertIn('Apply your trim before changing timeline zoom', script)
