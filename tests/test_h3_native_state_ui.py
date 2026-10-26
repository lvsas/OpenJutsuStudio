"""CPU-only native H3 frontend contracts; no app writes or inference."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class H3NativeStateUITests(unittest.TestCase):
    def test_native_capture_has_h3_scoped_touch_target(self):
        css = (ROOT / 'src/static/h3-studio.css').read_text()
        self.assertRegex(css, r'\[data-engine="h3"\] label\[for="h3-native-capture"\][^{]*\{[^}]*min-height:\s*44px')
        self.assertRegex(css, r'\[data-engine="h3"\] #h3-native-capture[^\{]*\{[^}]*width:\s*20px')

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
