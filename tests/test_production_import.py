"""Production module path must work without the test runner's src-path injection."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProductionImportTests(unittest.TestCase):
    def test_uvicorn_module_import_with_a_clean_pythonpath(self):
        with tempfile.TemporaryDirectory() as root:
            env = os.environ.copy()
            env.pop('PYTHONPATH', None)
            env['OPENGENJUTSU_WORK'] = str(Path(root)/'work')
            result = subprocess.run([sys.executable, '-c',
                'import src.app; from fastapi.testclient import TestClient; assert TestClient(src.app.app).get("/settings").status_code==200; print("production module OK")'],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('production module OK', result.stdout)
