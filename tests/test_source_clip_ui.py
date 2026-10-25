"""Exercise the shared production controller and LTX adapter without a GPU."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node is required for browser-controller contracts')
class SourceClipUITests(unittest.TestCase):
    def test_shared_controller_and_ltx_adapter(self):
        for name in ('h3_source_clip_contract.mjs', 'source_clip_ltx.mjs'):
            with self.subTest(script=name):
                result = subprocess.run(['node', '--experimental-default-type=module', str(ROOT/'tests'/name)],
                                        capture_output=True, text=True, timeout=30, cwd=ROOT)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
