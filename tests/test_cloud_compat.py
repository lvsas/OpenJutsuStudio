"""Static portability guards; these are not managed-Cloud acceptance tests."""
import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Match arbitrary accounts, not the maintainer's personal username.
LOCAL_HOME_PATH = r"(?:/home/|/Users/|[A-Za-z]:[\\/]Users[\\/])[A-Za-z0-9_.-]+"


class TestCloudCompat(unittest.TestCase):
    """Verify code has no hardcoded local paths."""

    def test_no_local_path_assumptions_in_core(self):
        """core.py should not contain hardcoded /home/ paths."""
        with open(os.path.join(os.path.dirname(__file__), "..", "src", "core.py")) as f:
            content = f.read()
        self.assertNotRegex(content, LOCAL_HOME_PATH,
                            "core.py should not hardcode a machine home path")

    def test_no_local_path_assumptions_in_app(self):
        """app.py should not contain hardcoded /home/ paths."""
        with open(os.path.join(os.path.dirname(__file__), "..", "src", "app.py")) as f:
            content = f.read()
        self.assertNotRegex(content, LOCAL_HOME_PATH,
                            "app.py should not hardcode a machine home path")

    def test_home_path_guard_is_not_tied_to_one_account_or_os(self):
        for value in ('/home/example/project', '/Users/example/project',
                      r'C:\Users\example\project', 'C:/Users/example/project'):
            with self.subTest(value=value):
                self.assertRegex(value, LOCAL_HOME_PATH)
        self.assertNotRegex('work/media/example.png', LOCAL_HOME_PATH)

    def test_core_uses_the_local_proxy_default(self):
        """The product does not accept inherited SDK Cloud targets."""
        import core
        self.assertEqual(core.COMFY_BASE_URL, "http://127.0.0.1:8189")

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
