"""Integration test: run_pipeline with multi-segment editing."""
import unittest
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import run_pipeline, Job


class TestPipelineWithCuts(unittest.TestCase):
    """Test that run_pipeline uses detect_scenes + edit_segment + merge_segments."""

    TEST_VIDEO = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "projects", "higgsfield-oss", "prototypes", "test_input_downloaded.mp4"
    )

    def test_pipeline_detects_cuts_and_edits_per_segment(self):
        """Pipeline should detect cuts, edit each segment, then merge."""
        if not os.path.exists(self.TEST_VIDEO):
            self.skipTest(f"Test video not found: {self.TEST_VIDEO}")

        job = Job(id="test-001", prompt="Replace riders with knights")

        mock_client = MagicMock()
        mock_engine = MagicMock()
        mock_engine.edit_frame.return_value = "edited.png"
        mock_engine.propagate.return_value = "seg_result.mp4"

        with patch("core.make_client", return_value=mock_client), \
             patch("core.ENGINES", {"ltx25-ripple": mock_engine}), \
             patch("core.detect_scenes") as mock_detect, \
             patch("core.edit_segment") as mock_edit, \
             patch("core.merge_segments") as mock_merge:

            mock_detect.return_value = [
                {"start": 0, "end": 67},
                {"start": 68, "end": 120}
            ]
            mock_edit.side_effect = ["seg1.mp4", "seg2.mp4"]
            mock_merge.return_value = "final_merged.mp4"

            run_pipeline(job, self.TEST_VIDEO, {"prompt": "Replace riders with knights"})

            self.assertEqual(mock_detect.call_count, 1, "detect_scenes called once")
            self.assertEqual(mock_edit.call_count, 2, "edit_segment called per segment")
            mock_merge.assert_called_once()
            self.assertEqual(job.status, "done")
            self.assertEqual(job.result, "final_merged.mp4")

    def test_pipeline_single_segment_no_merge(self):
        """Single segment → edit once, no merge needed."""
        if not os.path.exists(self.TEST_VIDEO):
            self.skipTest(f"Test video not found: {self.TEST_VIDEO}")

        job = Job(id="test-002", prompt="Replace with dragon")

        mock_client = MagicMock()
        mock_engine = MagicMock()
        mock_engine.edit_frame.return_value = "edited.png"
        mock_engine.propagate.return_value = "result.mp4"

        with patch("core.make_client", return_value=mock_client), \
             patch("core.ENGINES", {"ltx25-ripple": mock_engine}), \
             patch("core.detect_scenes") as mock_detect, \
             patch("core.edit_segment") as mock_edit, \
             patch("core.merge_segments") as mock_merge:

            mock_detect.return_value = [{"start": 0, "end": 120}]
            mock_edit.return_value = "result.mp4"

            run_pipeline(job, self.TEST_VIDEO, {"prompt": "test"})

            self.assertEqual(mock_edit.call_count, 1)
            # merge_segments should NOT be called for single segment
            mock_merge.assert_not_called()
            self.assertEqual(job.status, "done")

    def test_pipeline_upscales_after_merge(self):
        """Pipeline should upscale after merging segments."""
        if not os.path.exists(self.TEST_VIDEO):
            self.skipTest(f"Test video not found: {self.TEST_VIDEO}")

        job = Job(id="test-004", prompt="Replace riders with knights")

        mock_client = MagicMock()
        mock_engine = MagicMock()
        mock_engine.edit_frame.return_value = "edited.png"
        mock_engine.propagate.return_value = "seg_result.mp4"

        with patch("core.make_client", return_value=mock_client), \
             patch("core.ENGINES", {"ltx25-ripple": mock_engine}), \
             patch("core.detect_scenes") as mock_detect, \
             patch("core.edit_segment") as mock_edit, \
             patch("core.merge_segments") as mock_merge, \
             patch("core.upscale_video") as mock_upscale:

            mock_detect.return_value = [{"start": 0, "end": 120}]
            mock_edit.return_value = "seg.mp4"
            mock_merge.return_value = "merged.mp4"
            mock_upscale.return_value = "upscaled.mp4"

            run_pipeline(job, self.TEST_VIDEO, {"prompt": "test", "upscale": True})

            mock_upscale.assert_called_once()
            self.assertEqual(job.status, "done")
            self.assertEqual(job.result, "upscaled.mp4")

    def test_pipeline_handles_empty_video(self):
        """Empty video → error status."""
        job = Job(id="test-003")

        with patch("core.detect_scenes") as mock_detect:
            mock_detect.return_value = []
            run_pipeline(job, self.TEST_VIDEO, {})
            self.assertEqual(job.status, "error")
            self.assertIn("no scenes", job.error.lower())


if __name__ == "__main__":
    unittest.main()
