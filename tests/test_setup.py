"""Bootstrap/launcher contracts, without installing packages or contacting a GPU."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="opengenjutsu-setup-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "fresh checkout"
        self.root.mkdir()
        # Deliberately never copy the source .venv (it can be an absolute symlink).
        shutil.copytree(ROOT / "scripts", self.root / "scripts")
        shutil.copy2(ROOT / "requirements.txt", self.root / "requirements.txt")
        self.bin = self.root / "tools"
        self.bin.mkdir()
        for name in ("bash", "dirname", "mkdir", "cp"):
            executable = shutil.which(name)
            self.assertIsNotNone(executable, f"Required test tool: {name}")
            assert executable is not None
            (self.bin / name).symlink_to(executable)
        for name in ("ffmpeg", "ffprobe"):
            self.tool(name, "#!/usr/bin/env bash\nexit 0\n")
        self.python_stub = self.tool("fake-python", """#!/usr/bin/env bash
if [[ "${1:-}" == -c ]]; then
  [[ "${FAKE_PYTHON_VERSION:-3.12}" == 3.12 ]]
  exit $?
fi
printf 'PYTHONPATH=%s\\n' "${PYTHONPATH-unset}"
printf 'ARG=%s\\n' "$@"
""")
        self.tool("uv", """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$UV_LOG"
printf '%s\\n' "${PYTHONPATH-unset}" >> "$ENV_LOG"
if [[ "$1" == venv ]]; then
  mkdir -p .venv/bin
  cp "$PYTHON_STUB" .venv/bin/python
fi
""")
        self.env = dict(os.environ, PATH=str(self.bin), PYTHONPATH="/foreign/python",
                        UV_LOG=str(self.root / "uv.log"),
                        ENV_LOG=str(self.root / "env.log"),
                        PYTHON_STUB=str(self.python_stub))
        self.env.pop("FAKE_PYTHON_VERSION", None)

    def tool(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)
        return path

    def run_script(self, name="setup.sh", *args):
        return subprocess.run([str(self.bin / "bash"), str(self.root / "scripts" / name), *args],
                              cwd=self.tmp.name, env=self.env, text=True,
                              capture_output=True, timeout=15)

    def log(self):
        path = self.root / "uv.log"
        return path.read_text() if path.exists() else ""

    def existing_python(self):
        target = self.root / ".venv" / "bin"
        target.mkdir(parents=True)
        shutil.copy2(self.python_stub, target / "python")

    def test_fresh_setup_uses_python312_and_no_implicit_proxy(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("venv .venv --python 3.12", self.log())
        self.assertIn("pip install --python .venv/bin/python -r requirements.txt", self.log())
        self.assertNotIn("comfy-api-proxy", self.log())
        self.assertFalse((self.root / ".venv").is_symlink())
        self.assertTrue((self.root / "work" / "jobs").is_dir())
        self.assertEqual(set((self.root / "env.log").read_text().splitlines()), {"unset"})

    def test_proxy_install_is_explicit_opt_in(self):
        result = self.run_script("setup.sh", "--with-proxy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pip install --python .venv/bin/python comfy-api-proxy==0.1.6", self.log())

    def test_existing_python312_is_reused(self):
        self.existing_python()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("venv .venv", self.log())

    def test_wrong_python_is_rejected_without_install_or_replacement(self):
        self.existing_python()
        before = (self.root / ".venv/bin/python").read_bytes()
        self.env["FAKE_PYTHON_VERSION"] = "3.11"
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 3.12", result.stderr)
        self.assertEqual(self.log(), "")
        self.assertEqual((self.root / ".venv/bin/python").read_bytes(), before)

    def test_missing_media_tools_fail_before_install(self):
        for name in ("ffmpeg", "ffprobe"):
            with self.subTest(name=name):
                path = self.bin / name
                original = path.read_text()
                path.unlink()
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)
                self.assertIn("FFmpeg", result.stderr)
                self.assertEqual(self.log(), "")
                self.tool(name, original)

    def test_missing_uv_is_actionable(self):
        (self.bin / "uv").unlink()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("https://docs.astral.sh/uv/", result.stderr)

    def test_help_does_not_install(self):
        result = self.run_script("setup.sh", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--with-proxy", result.stdout)
        self.assertEqual(self.log(), "")

    def test_unknown_option_fails_before_install(self):
        result = self.run_script("setup.sh", "--typo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--typo", result.stderr)
        self.assertEqual(self.log(), "")

    def test_broken_venv_symlink_is_never_overwritten(self):
        target = self.root / "missing environment"
        (self.root / ".venv").symlink_to(target)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".venv", result.stderr)
        self.assertEqual(self.log(), "")
        self.assertEqual((self.root / ".venv").readlink(), target)

    def test_launcher_requires_setup(self):
        result = self.run_script("run_app.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bash scripts/setup.sh", result.stderr)

    def test_launcher_rejects_wrong_python(self):
        self.existing_python()
        self.env["FAKE_PYTHON_VERSION"] = "3.11"
        result = self.run_script("run_app.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 3.12", result.stderr)
        self.assertNotIn("ARG=-m", result.stdout)

    def test_launcher_is_loopback_and_isolated_from_caller(self):
        self.existing_python()
        self.env["OPENGENJUTSU_PORT"] = "8123"
        result = self.run_script("run_app.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PYTHONPATH=unset", result.stdout)
        args = [line.removeprefix("ARG=") for line in result.stdout.splitlines()
                if line.startswith("ARG=")]
        self.assertEqual(args, ["-m", "uvicorn", "src.app:app", "--app-dir", str(self.root),
                                "--host", "127.0.0.1", "--port", "8123"])


if __name__ == "__main__":
    unittest.main()
