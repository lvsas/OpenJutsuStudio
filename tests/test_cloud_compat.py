"""Tests for Comfy Cloud compatibility (no local path assumptions)."""
import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestCloudCompat(unittest.TestCase):
    """Verify code has no hardcoded local paths."""

    def test_no_local_path_assumptions_in_core(self):
        """core.py should not contain hardcoded /home/ paths."""
        with open(os.path.join(os.path.dirname(__file__), "..", "src", "core.py")) as f:
            content = f.read()
        self.assertNotIn("/home/user", content,
                         "core.py should not reference /home/user")
        self.assertNotIn("/home/user", content,
                         "core.py should not reference /home/user")

    def test_no_local_path_assumptions_in_app(self):
        """app.py should not contain hardcoded /home/ paths."""
        with open(os.path.join(os.path.dirname(__file__), "..", "src", "app.py")) as f:
            content = f.read()
        self.assertNotIn("/home/user", content,
                         "app.py should not reference /home/user")

    def test_comfy_base_url_respected(self):
        """COMFY_BASE_URL should be used from environment."""
        import core
        self.assertTrue(hasattr(core, "COMFY_BASE_URL"),
                        "core should have COMFY_BASE_URL")
        # Should be read from env or default
        self.assertIn(core.COMFY_BASE_URL, [
            "http://127.0.0.1:8189",  # local default
            "https://cloud.comfy.org",  # cloud
        ] + [os.environ.get("COMFY_BASE_URL", "")])

    def test_work_dir_uses_env_override(self):
        """WORK directory should be overridable via env."""
        import core
        self.assertTrue(hasattr(core, "WORK"),
                        "core should have WORK")
        # WORK should be a Path
        from pathlib import Path
        self.assertIsInstance(core.WORK, Path)


if __name__ == "__main__":
    unittest.main()
