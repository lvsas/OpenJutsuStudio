"""Shared modal decisions have a real JS execution contract, not just markup assertions."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ShareReelUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for the UI behavior contract")
    def test_preview_share_behavior_contract(self):
        root = Path(__file__).resolve().parents[1]
        run = subprocess.run(["node", "tests/share_reel_ui_contract.mjs"], cwd=root,
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("URL validation PASS", run.stdout)
        self.assertIn("explicit X intent, opt-in contest caption", run.stdout)
