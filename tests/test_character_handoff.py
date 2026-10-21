import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CharacterHandoffTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required for browser-state contract')
    def test_transfer_behavior(self):
        result = subprocess.run(['node', '--experimental-default-type=module',
                                 'tests/character_handoff_contract.mjs'],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_both_swap_studios_consume_character_id_without_submission(self):
        ltx = (ROOT / 'src/static/app.js').read_text()
        h3 = (ROOT / 'src/static/h3-studio.js').read_text()
        for script in (ltx, h3):
            self.assertIn('applyCharacterReference', script)
            self.assertIn("character-handoff.js", script)
        self.assertIn('isBusy: () => Boolean(activeJob)', ltx)
        self.assertIn('isBusy: () => pending || take.active', h3)

    def test_timeline_navigation_is_present_in_existing_swap_shells(self):
        for name in ('index.html', 'h3.html'):
            markup = (ROOT / 'src/templates' / name).read_text()
            self.assertIn('href="/timeline"', markup)
