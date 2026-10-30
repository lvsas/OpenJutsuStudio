"""The install validator must fail loudly on a machine that is not ready."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('validate_install', ROOT / 'scripts' / 'validate_install.py')
validate = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(validate)


class ValidateInstall(unittest.TestCase):
    def test_a_missing_venv_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = validate.inspect(Path(tmp))
        self.assertFalse(report['checks']['venv'])
        self.assertTrue(any('venv' in line for line in report['problems']))

    def test_a_comfyui_without_custom_nodes_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = validate.inspect(Path(tmp), comfyui=Path(tmp))
        self.assertTrue(any('custom_nodes' in line for line in report['problems']))

    def test_missing_node_packs_are_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            comfy = Path(tmp)
            (comfy / 'custom_nodes').mkdir()
            report = validate.inspect(ROOT, comfyui=comfy)
        self.assertGreater(report['missing_packs'], 0)
        self.assertTrue(any('pack' in line for line in report['problems']))

    def test_a_ready_tree_reports_no_venv_problem(self):
        report = validate.inspect(ROOT)
        self.assertTrue(report['checks']['manifest'])
        self.assertTrue(report['checks']['ffmpeg'])


if __name__ == '__main__':
    unittest.main()
