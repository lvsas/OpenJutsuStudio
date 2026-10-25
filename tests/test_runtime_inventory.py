from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app
from fastapi.testclient import TestClient


class RuntimeInventoryTests(unittest.TestCase):
    def test_inventory_exposes_declared_local_runtime_without_a_live_gpu(self):
        response = TestClient(app.app).get("/api/runtime-inventory")
        self.assertEqual(response.status_code, 200, response.text)
        inventory = response.json()
        self.assertEqual(inventory["engine"], "ltx25-ripple")
        self.assertEqual(inventory["inference"]["mode"], "configurable-api-v2")
        self.assertFalse(inventory["inference"]["hosted_render_verified"])
        self.assertIn("comfy-cloud", inventory["inference"]["supported_target_modes"])
        self.assertIn("Settings", inventory["inference"]["target_selection"])
        self.assertIn("OPENGENJUTSU_COMFY_BASE_URL", inventory["inference"]["target_selection"])
        self.assertIn("LTX25_Ripple_v11.safetensors", inventory["declared_model_files"].values())
        self.assertIn("VHS_VideoCombine", inventory["declared_workflow_nodes"])
        self.assertIn("model licensing", inventory["verification"]["what_it_does_not_prove"])


if __name__ == "__main__":
    unittest.main()
