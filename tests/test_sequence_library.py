"""Discovery is a projection, never an import or native-state conversion."""
import shutil
import subprocess
import unittest
from pathlib import Path


class SequenceLibraryContracts(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is needed for browser contracts')
    def test_native_and_swap_discovery(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', str(root / 'tests/sequence_library.mjs')],
                                cwd=root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for browser contracts')
    def test_typed_source_identity_and_placements(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', '--experimental-default-type=module', '--test',
                                 str(root / 'tests/sequence_sources_contract.mjs')],
                                cwd=root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
