from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graphs import build_ripple
from job_api import JobAPI


class RippleDefaultTests(unittest.TestCase):
    def test_product_defaults_use_validated_identity_strength(self):
        graph = build_ripple("source.mp4", "first-frame.png")
        self.assertEqual(graph["1312"]["inputs"]["strength_model"], 1.35)
        api_default = inspect.signature(JobAPI.create_job).parameters["ripple_strength"].default
        self.assertEqual(api_default.default, 1.35)
        template = (Path(__file__).resolve().parents[1] / "src/templates/index.html").read_text()
        self.assertIn('name="ripple_strength"', template)
        self.assertIn('value="1.35"', template)


if __name__ == "__main__":
    unittest.main()
