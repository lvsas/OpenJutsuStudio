"""Unit contracts for canonical Take discovery and honest duration refusals."""
from pathlib import Path
import shutil
import subprocess
import unittest


class NativeContinuationRecoveryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required for browser contracts')
    def test_provenance_draft_preservation_and_duration_messages(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ['node', '--experimental-default-type=module', '--test',
             'tests/sequence_native_recovery_contract.mjs'],
            cwd=root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_one_existing_handoff_without_an_ancillary_recovery_controller(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / 'src/templates/timeline.html').read_text()
        self.assertIn('id="native-handoff-add"', template)
        self.assertNotIn('id="position-native-choices"', template)
