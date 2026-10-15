"""Tests for scene detection (shot boundary detection)."""
import unittest
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import detect_scenes


class TestDetectScenes(unittest.TestCase):
    """Test scene detection on the known test clip (cut at frame 68)."""

    TEST_VIDEO = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "projects", "higgsfield-oss", "prototypes", "test_input_downloaded.mp4"
    )

    def test_detects_cut_at_frame_68(self):
        """The test clip has a known cut at frame 68 (±5)."""
        if not os.path.exists(self.TEST_VIDEO):
            self.skipTest(f"Test video not found: {self.TEST_VIDEO}")
        scenes = detect_scenes(self.TEST_VIDEO)
        self.assertGreater(len(scenes), 1, "Should detect at least 2 scenes")
        # First cut should be near frame 68
        first_cut = scenes[1]["start"] if len(scenes) > 1 else None
        self.assertIsNotNone(first_cut)
        self.assertTrue(
            60 <= first_cut <= 75,
            f"First cut at frame {first_cut}, expected 60-75"
        )

    def test_no_cut_returns_single_segment(self):
        """A video without cuts returns a single segment."""
        # Create a tiny test video without cuts
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            tmp = f.name
        try:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10",
                "-c:v", "libx264", tmp
            ], capture_output=True, check=True)
            scenes = detect_scenes(tmp)
            self.assertEqual(len(scenes), 1, "No cut → single segment")
            self.assertEqual(scenes[0]["start"], 0)
        finally:
            os.unlink(tmp)

    def test_detects_scenes_returns_valid_ranges(self):
        """All segments have valid start/end ranges."""
        if not os.path.exists(self.TEST_VIDEO):
            self.skipTest(f"Test video not found: {self.TEST_VIDEO}")
        scenes = detect_scenes(self.TEST_VIDEO)
        for i, seg in enumerate(scenes):
            self.assertIn("start", seg)
            self.assertIn("end", seg)
            self.assertLess(seg["start"], seg["end"], f"Segment {i}: start >= end")
        # Segments should be contiguous
        for i in range(len(scenes) - 1):
            self.assertEqual(
                scenes[i]["end"] + 1, scenes[i + 1]["start"],
                f"Gap between segment {i} and {i+1}"
            )


if __name__ == "__main__":
    unittest.main()
