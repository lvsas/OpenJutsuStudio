"""Test for per-segment editing (extract → edit → propagate)."""
import unittest
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import edit_segment, Job, WORK


class TestEditSegment(unittest.TestCase):
    """Test editing a single segment."""

    TEST_VIDEO = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "projects", "higgsfield-oss", "prototypes", "test_input_downloaded.mp4"
    )

    def test_edit_segment_produces_output(self):
        """edit_segment should return a path to edited segment video."""
        if not os.path.exists(self.TEST_VIDEO):
            self.skipTest(f"Test video not found: {self.TEST_VIDEO}")

        mock_client = MagicMock()
        mock_engine = MagicMock()
        mock_engine.edit_frame.return_value = "edited_frame.png"
        mock_engine.propagate.return_value = "edited_segment.mp4"

        with patch("core.make_client", return_value=mock_client), \
             patch("core.ENGINES", {"ltx25-ripple": mock_engine}):
            result = edit_segment(
                video_path=self.TEST_VIDEO,
                segment={"start": 0, "end": 67},
                prompt="Replace riders with knights",
                client=mock_client,
                engine=mock_engine
            )
            self.assertIsNotNone(result)
            self.assertTrue(result.endswith(".mp4"))
            mock_engine.edit_frame.assert_called_once()
            mock_engine.propagate.assert_called_once()

    def test_edit_segment_empty_segment_raises(self):
        """Empty segment (start >= end) should raise ValueError."""
        with self.assertRaises(ValueError):
            edit_segment(
                video_path=self.TEST_VIDEO,
                segment={"start": 10, "end": 5},
                prompt="test",
                client=MagicMock(),
                engine=MagicMock()
            )

    def test_edit_segment_calls_edit_with_prompt(self):
        """edit_frame should receive the prompt."""
        mock_client = MagicMock()
        mock_engine = MagicMock()
        mock_engine.edit_frame.return_value = "edited.png"
        mock_engine.propagate.return_value = "result.mp4"

        with patch("core.make_client", return_value=mock_client), \
             patch("core.ENGINES", {"ltx25-ripple": mock_engine}):
            edit_segment(
                video_path=self.TEST_VIDEO,
                segment={"start": 0, "end": 10},
                prompt="Replace with a dragon",
                client=mock_client,
                engine=mock_engine
            )
            call_args = mock_engine.edit_frame.call_args
            self.assertIn("dragon", call_args[0][2])


if __name__ == "__main__":
    unittest.main()
