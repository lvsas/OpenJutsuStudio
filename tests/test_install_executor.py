"""The executor installer must refuse what it cannot verify."""
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('install_executor', ROOT / 'scripts' / 'install_executor.py')
installer = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(installer)


def fake_response(blob: bytes):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None
    return Response(blob)


class ExecutorInstallTests(unittest.TestCase):
    def test_plan_reports_present_and_missing_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            comfy = Path(tmp)
            (comfy / 'custom_nodes' / 'ComfyUI-VideoHelperSuite').mkdir(parents=True)
            rows = installer.plan([
                {'name': 'ComfyUI-VideoHelperSuite', 'required': True,
                 'install': {'kind': 'registry', 'package_url': 'https://example.invalid/a.zip'}},
                {'name': 'ComfyUI-LTXVideo', 'required': True,
                 'source': 'https://github.com/Lightricks/ComfyUI-LTXVideo'},
            ], comfy)
        self.assertEqual(rows[0]['state'], 'present')
        self.assertEqual(rows[1]['state'], 'missing')
        self.assertEqual(rows[1]['kind'], 'git')

    def test_a_pack_without_a_source_is_reported_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = installer.plan([{'name': 'ghost', 'required': True}], Path(tmp))
        self.assertEqual(rows[0]['state'], 'unavailable')

    def test_a_archive_whose_hash_does_not_match_is_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('pack/__init__.py', '')
        row = {'name': 'pack', 'package_url': 'https://example.invalid/p.zip',
               'package_sha256': '0' * 64,
               'target': Path(tempfile.mkdtemp()) / 'custom_nodes' / 'pack'}
        with patch.object(installer.urllib.request, 'urlopen', return_value=fake_response(buffer.getvalue())):
            with self.assertRaises(ValueError):
                installer.install_registry(row)
        self.assertFalse(row['target'].exists())

    def test_an_archive_that_escapes_the_target_is_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('../../escape.py', 'x')
        blob = buffer.getvalue()
        import hashlib
        row = {'name': 'pack', 'package_url': 'https://example.invalid/p.zip',
               'package_sha256': hashlib.sha256(blob).hexdigest(),
               'target': Path(tempfile.mkdtemp()) / 'custom_nodes' / 'pack'}
        with patch.object(installer.urllib.request, 'urlopen', return_value=fake_response(blob)):
            with self.assertRaises(ValueError):
                installer.install_registry(row)


if __name__ == '__main__':
    unittest.main()
