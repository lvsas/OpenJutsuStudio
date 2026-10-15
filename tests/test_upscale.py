"""Tests for video upscale (spatial x2)."""
import unittest
import os
import sys
import subprocess
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import upscale_video


class TestUpscale(unittest.TestCase):
    """Test upscaling video resolution."""

    def _create_test_video(self, path: str, width: int = 320, height: int = 240):
        """Create a tiny test video with ffmpeg."""
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration=1:size={width}x{height}:rate=10",
            "-c:v", "libx264", str(path)
        ], capture_output=True, check=True)

    def test_upscale_doubles_resolution(self):
        """Upscaling x2 should double width and height."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp4")
            output_path = os.path.join(tmpdir, "output.mp4")
            self._create_test_video(input_path, width=320, height=240)
            upscale_video(input_path, output_path, scale=2.0)
            self.assertTrue(os.path.exists(output_path), "Output file should exist")
            # Check resolution
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "json", output_path],
                capture_output=True, text=True, check=True
            )
            import json
            info = json.loads(probe.stdout)
            stream = info["streams"][0]
            self.assertEqual(stream["width"], 640, "Width should double")
            self.assertEqual(stream["height"], 480, "Height should double")

    def test_upscale_preserves_frame_count(self):
        """Upscaling should not change frame count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input.mp4")
            output_path = os.path.join(tmpdir, "output.mp4")
            self._create_test_video(input_path)
            # Count input frames
            probe_in = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=nb_frames", "-of", "json", input_path],
                capture_output=True, text=True, check=True
            )
            import json
            in_frames = int(json.loads(probe_in.stdout)["streams"][0]["nb_frames"])
            upscale_video(input_path, output_path, scale=2.0)
            probe_out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=nb_frames", "-of", "json", output_path],
                capture_output=True, text=True, check=True
            )
            out_frames = int(json.loads(probe_out.stdout)["streams"][0]["nb_frames"])
            self.assertEqual(in_frames, out_frames, "Frame count preserved")

    def test_upscale_empty_input_raises(self):
        """Non-existent input should raise FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            upscale_video("/nonexistent/video.mp4", "/tmp/out.mp4")


if __name__ == "__main__":
    unittest.main()
