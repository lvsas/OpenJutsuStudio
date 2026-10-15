"""Terminal states must be persisted, including failures and client lifetime."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import core


class PipelineStateTests(unittest.TestCase):
    def run_case(self, *, failure=False, empty=False):
        root = Path(self.tmp.name)
        client = MagicMock()
        with patch.object(core, "WORK", root), \
             patch.object(core, "make_client", return_value=client), \
             patch.object(core, "detect_scenes", return_value=[] if empty else [{"start": 0, "end": 8}]), \
             patch.object(core, "edit_segment", side_effect=RuntimeError("render failed") if failure else None,
                          return_value="result.mp4"):
            job = core.Job(id="case", prompt="edit")
            core.run_pipeline(job, Path("source.mp4"), {})
            saved = core.Job.load(job.id)
        return saved, client

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_success_persisted_and_client_closed(self):
        job, client = self.run_case()
        self.assertEqual(job.status, "done")
        self.assertEqual(job.result, "result.mp4")
        self.assertEqual(job.progress, 1.0)
        self.assertIsNotNone(job.finished)
        client.close.assert_called_once()

    def test_failure_persisted_and_client_closed(self):
        job, client = self.run_case(failure=True)
        self.assertEqual(job.status, "error")
        self.assertIn("render failed", job.error)
        self.assertIsNotNone(job.finished)
        client.close.assert_called_once()

    def test_padding_is_reported_per_shot(self):
        with (
            patch.object(core, "WORK", Path(self.tmp.name)),
            patch.object(core, "make_client", return_value=MagicMock()),
            patch.object(core, "detect_scenes", return_value=[
                {"start": 0, "end": 67}, {"start": 68, "end": 120}]),
            patch.object(core, "edit_segment", return_value="shot.mp4"),
            patch.object(core, "merge_segments", return_value="merged.mp4"),
        ):
            job = core.Job(id="padding")
            core.run_pipeline(job, Path("source.mp4"), {})
            shots = core.Job.load(job.id).meta["shots"]
        self.assertEqual([s["source_frames"] for s in shots], [68, 53])
        self.assertEqual([s["inference_frames"] for s in shots], [73, 57])
        self.assertEqual([s["padding_frames"] for s in shots], [5, 4])

    def test_no_scenes_finishes_without_constructing_client(self):
        job, client = self.run_case(empty=True)
        self.assertEqual(job.status, "error")
        self.assertIsNotNone(job.finished)
        client.close.assert_not_called()
