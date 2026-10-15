"""Tests for segment merging (concatenation)."""
import unittest
import os
import sys
import subprocess
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import merge_segments


class TestMergeSegments(unittest.TestCase):
    """Test merging multiple segment videos into one."""

    def _create_test_video(self, path: str, duration: int = 1, color: str = "red"):
        """Create a tiny test video with ffmpeg."""
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=64x64:rate=10",
            "-c:v", "libx264", str(path)
        ], capture_output=True, check=True)

    def test_merge_two_segments(self):
        """Two segments → one merged video."""
        with tempfile.TemporaryDirectory() as tmpdir:
            seg1 = os.path.join(tmpdir, "seg1.mp4")
            seg2 = os.path.join(tmpdir, "seg2.mp4")
            self._create_test_video(seg1, duration=1, color="red")
            self._create_test_video(seg2, duration=1, color="blue")
            result = merge_segments([seg1, seg2])
            self.assertTrue(os.path.exists(result), "Merged file should exist")
            # Check frame count
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=nb_frames", "-of", "json", result],
                capture_output=True, text=True, check=True
            )
            import json
            info = json.loads(probe.stdout)
            frames = int(info["streams"][0]["nb_frames"])
            self.assertGreater(frames, 0, "Merged video should have frames")

    def test_merge_empty_list_returns_none(self):
        """Empty segment list → None."""
        result = merge_segments([])
        self.assertIsNone(result)

    def test_merge_single_segment_returns_it(self):
        """Single segment → return it directly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            seg = os.path.join(tmpdir, "seg.mp4")
            self._create_test_video(seg)
            result = merge_segments([seg])
            self.assertEqual(result, seg)

    def test_merge_preserves_frame_count(self):
        """Merged video has sum of all segment frames."""
        with tempfile.TemporaryDirectory() as tmpdir:
            segs = []
            total_frames = 0
            for i in range(3):
                seg = os.path.join(tmpdir, f"seg{i}.mp4")
                self._create_test_video(seg, duration=1)
                segs.append(seg)
                # Count frames
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=nb_frames", "-of", "json", seg],
                    capture_output=True, text=True, check=True
                )
                info = json.loads(probe.stdout)
                total_frames += int(info["streams"][0]["nb_frames"])
            result = merge_segments(segs)
            self.assertTrue(os.path.exists(result))
            # Verify total frames
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=nb_frames", "-of", "json", result],
                capture_output=True, text=True, check=True
            )
            info = json.loads(probe.stdout)
            merged_frames = int(info["streams"][0]["nb_frames"])
            self.assertEqual(merged_frames, total_frames, "Frame count preserved")


if __name__ == "__main__":
    unittest.main()
