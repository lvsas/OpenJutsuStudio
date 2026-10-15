"""Real CPU/FFmpeg segment frame extraction; no inference or external media."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core import detect_scenes, extract_segment_frames
from tests.media_fixtures import TOTAL_FRAMES, TWO_SHOTS, make_test_video


class TestExtractSegmentFrames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.video = make_test_video(Path(temporary.name))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "frames"

    def extract(self, scenes):
        return extract_segment_frames(self.video, scenes, output_dir=self.output)

    def test_extracts_one_frame_per_segment(self):
        """The known two shots each produce one frame in the temp directory."""
        scenes = detect_scenes(self.video)
        self.assertEqual(scenes, TWO_SHOTS)
        frames = self.extract(scenes)
        self.assertEqual(len(frames), 2)
        self.assertEqual([frame.parent for frame in frames], [self.output] * 2)

    def test_extracted_frames_exist(self):
        """Decoded first frames are black then white, proving shot selection."""
        frames = self.extract(TWO_SHOTS)
        self.assertEqual(len(frames), 2)
        for frame, expected in zip(frames, (0, 255)):
            with self.subTest(frame=frame):
                self.assertTrue(frame.is_file())
                self.assertGreater(frame.stat().st_size, 0)
                pixels = subprocess.run(
                    ["ffmpeg", "-nostdin", "-v", "error", "-i", str(frame),
                     "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                    capture_output=True, check=True, timeout=30,
                ).stdout
                self.assertTrue(pixels)
                self.assertLessEqual(abs(sum(pixels) / len(pixels) - expected), 2)

    def test_no_scenes_returns_empty(self):
        self.assertEqual(self.extract([]), [])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_single_segment_returns_single_frame(self):
        frames = self.extract([{"start": 0, "end": TOTAL_FRAMES - 1}])
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].is_file())
        self.assertEqual(frames[0].parent, self.output)


if __name__ == "__main__":
    unittest.main()
