"""Job storage uses atomic replacements and disallows path traversal."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import core


class JobStorageTests(unittest.TestCase):
    def test_job_save_replaces_complete_json_atomically(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(core, "WORK", Path(tmp)):
            replace = Path.replace
            with patch.object(Path, "replace", autospec=True, side_effect=replace) as observed:
                job = core.Job(id="valid-id")
                job.save()
                job.status = "done"
                job.save()
            self.assertEqual(observed.call_count, 2)
            self.assertEqual(json.loads(job.path.read_text())["status"], "done")
            self.assertEqual(list(job.path.parent.glob("*.tmp")), [])

    def test_job_load_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(core, "WORK", Path(tmp)):
            (Path(tmp) / "jobs").mkdir()
            (Path(tmp) / "outside.json").write_text(json.dumps({"id": "outside"}))
            with self.assertRaises(KeyError):
                core.Job.load("../outside")
