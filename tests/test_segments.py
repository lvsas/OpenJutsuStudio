"""Tests for segment frame extraction."""
import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import detect_scenes, extract_segment_frames


class TestExtractSegmentFrames(unittest.TestCase):
    """Test extracting first frame from each detected segment."""

    TEST_VIDEO = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "projects", "higgsfield-oss", "prototypes", "test_input_downloaded.mp4"
    )

    def test_extracts_one_frame_per_segment(self):
        """Each segment should produce exactly one frame."""
        if not os.path.exists(self.TEST_VIDEO):
            self.skipTest(f"Test video not found: {self.TEST_VIDEO}")
        scenes = detect_scenes(self.TEST_VIDEO)
        frames = extract_segment_frames(self.TEST_VIDEO, scenes)
        self.assertEqual(len(frames), len(scenes), "One frame per segment")

    def test_extracted_frames_exist(self):
        """All extracted frame files should exist on disk."""
        if not os.path.exists(self.TEST_VIDEO):
            self.skipTest(f"Test video not found: {self.TEST_VIDEO}")
        scenes = detect_scenes(self.TEST_VIDEO)
        frames = extract_segment_frames(self.TEST_VIDEO, scenes)
        for f in frames:
            self.assertTrue(os.path.exists(f), f"Frame file missing: {f}")

    def test_no_scenes_returns_empty(self):
        """Empty scene list → empty frame list."""
        frames = extract_segment_frames(self.TEST_VIDEO, [])
        self.assertEqual(len(frames), 0)

    def test_single_segment_returns_single_frame(self):
        """Single segment → single frame."""
        if not os.path.exists(self.TEST_VIDEO):
            self.skipTest(f"Test video not found: {self.TEST_VIDEO}")
        scenes = [{"start": 0, "end": 100}]
        frames = extract_segment_frames(self.TEST_VIDEO, scenes)
        self.assertEqual(len(frames), 1)


if __name__ == "__main__":
    unittest.main()
