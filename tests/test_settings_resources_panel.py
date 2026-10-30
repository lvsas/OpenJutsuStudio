"""The Resources panel says what is missing, and never pretends to fix it.

Readiness is already answered by the backend; this contract keeps the panel
wired to it, keeps the commands visible, and states that nothing is installed
from a browser page.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / 'src' / 'templates' / 'settings.html').read_text()
SCRIPT = (ROOT / 'src' / 'static' / 'settings.js').read_text()


class ResourcesPanelTests(unittest.TestCase):
    def test_page_has_the_panel_and_its_targets(self):
        for identifier in ('resources-title', 'resources-summary', 'resources-missing'):
            self.assertIn(f'id="{identifier}"', PAGE, identifier)

    def test_panel_reads_the_backend_readiness_endpoint(self):
        self.assertIn("fetch('/api/readiness'", SCRIPT)
        self.assertIn('missing_nodes', SCRIPT)
        self.assertIn('missing_models', SCRIPT)

    def test_panel_lists_the_commands_it_does_not_run(self):
        self.assertIn('make deps COMFYUI=', PAGE)
        self.assertIn('make check', PAGE)
        self.assertIn('never installs', PAGE)


if __name__ == '__main__':
    unittest.main()
