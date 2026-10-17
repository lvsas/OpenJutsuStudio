from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app as app_module
from fastapi.testclient import TestClient


class TakeCapsuleUITests(unittest.TestCase):
    def test_capsule_is_opt_in_and_inspectable_in_completed_result_panel(self):
        client = TestClient(app_module.app)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('id="download-capsule"', html)
        self.assertIn('id="replay-capsule"', html)
        self.assertIn('id="capsule-details"', html)
        self.assertIn('id="take-story"', html)
        self.assertIn('id="anchor-stage"', html)
        self.assertIn('id="show-anchor"', html)
        self.assertIn('id="remove-reference"', html)
        self.assertIn('/static/take-visual-story.js', html)
        self.assertIn("Source/reference files are not bundled", html)
        self.assertIn("pixel-identical replay is not promised", html)
        self.assertIn('/static/take-capsule.js', html)
        self.assertIn('id="result-actions"', html)
        script = client.get("/static/take-capsule.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("/replay", script.text)


if __name__ == "__main__":
    unittest.main()
