"""CPU-only native H3 frontend contracts; no app writes or inference."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class H3NativeStateUITests(unittest.TestCase):
    def test_native_capture_is_always_on_not_an_advanced_choice(self):
        html = (ROOT / 'src/templates/h3.html').read_text()
        self.assertRegex(html, r'id="h3-native-capture" type="hidden" name="native_capture" value="true"')
        self.assertIn('Every swap saves its video and continuation state automatically.', html)
        self.assertNotIn('Save native state too', html)

    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_native_state_and_distinct_version_contract(self):
        result = subprocess.run(
            ['node', '--experimental-default-type=module', 'tests/h3_native_state.mjs'],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('explicit distinct-version choice passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
