"""Static HTML and isolated browser-controller contracts; no compute or server needed."""
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class SettingsUIContracts(unittest.TestCase):
    def test_settings_accessible_write_only_form(self):
        text = (ROOT / 'src/templates/settings.html').read_text()
        doc = Document(text)
        ids = {attrs['id']: (tag, attrs) for tag, attrs in doc.elements if 'id' in attrs}
        for name in ['settings-form', 'compute-url', 'compute-key', 'clear-key',
                     'key-status', 'settings-source', 'settings-status', 'test-status',
                     'test-results', 'test-connection', 'save-settings']:
            self.assertIn(name, ids)
        labels = {attrs.get('for') for tag, attrs in doc.elements if tag == 'label'}
        self.assertTrue({'compute-url', 'compute-key', 'clear-key'} <= labels)
        key = ids['compute-key'][1]
        self.assertEqual(key.get('type'), 'password')
        self.assertNotIn('value', key)
        self.assertEqual(key.get('autocomplete'), 'new-password')
        self.assertEqual(ids['test-connection'][1].get('type'), 'button')
        self.assertEqual(ids['save-settings'][1].get('type'), 'submit')
        self.assertEqual(ids['settings-status'][1].get('role'), 'status')
        self.assertEqual(ids['test-status'][1].get('aria-live'), 'polite')
        self.assertIn('https://docs.comfy.org/development/api-development/sdks', text)
        self.assertIn('comfy-api-proxy', text)
        self.assertIn('does not install or rename files', text.lower())
        self.assertNotIn('/static/project-session.js', text)  # Settings must only GET settings on entry.
        for asset in ['design-system.css', 'app.css', 'settings.css', 'settings.js']:
            self.assertIn('/static/' + asset, text)

    def test_settings_reachable_from_every_existing_header(self):
        for name in ['index', 'h3', 'character', 'timeline', 'assembly', 'settings']:
            with self.subTest(name=name):
                text = (ROOT / f'src/templates/{name}.html').read_text()
                doc = Document(text)
                links = [attrs for tag, attrs in doc.elements if tag == 'a' and attrs.get('href') == '/settings']
                self.assertEqual(len(links), 1)
                self.assertNotIn('hidden', links[0])
                self.assertIn('settings-utility', links[0].get('class', ''))
                self.assertNotIn('engine-chip', links[0].get('class', ''))
                self.assertEqual(links[0].get('aria-label'), 'Settings')
                header = text.split('<header class="site-header">', 1)[1].split('</header>', 1)[0]
                self.assertIn('class="header-utilities"', header)
                self.assertNotIn('href="/settings"', header.split('class="header-utilities"', 1)[0])
                self.assertNotRegex(header, r'>\s*Settings\s*<')
                self.assertIn('<svg', header.split('class="header-utilities"', 1)[1])
                self.assertIn('/static/settings.js', text)
                self.assertIn('/static/settings.css', text)

    def test_controller_has_no_secret_persistence_or_html_injection(self):
        js = (ROOT / 'src/static/settings.js').read_text()
        for forbidden in ['innerHTML', 'insertAdjacentHTML', 'localStorage', 'sessionStorage', 'console.', '/api/prompt']:
            self.assertNotIn(forbidden, js)
        css = (ROOT / 'src/static/settings.css').read_text()
        self.assertIn('flex-wrap: wrap', css)
        self.assertIn('minmax(0, 1fr)', css)
        self.assertIn('overflow-wrap: anywhere', css)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_node_controller_contracts(self):
        result = subprocess.run(
            ['node', '--experimental-default-type=module', '--test', 'tests/settings_contract.mjs'],
            cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
