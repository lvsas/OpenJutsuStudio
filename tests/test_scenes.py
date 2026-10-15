"""CPU scene detection tests using real synthetic FFmpeg media, not inference."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core import detect_scenes, ffprobe
from tests.media_fixtures import (
    CUT_FRAME, FRAME_RATE, FRAME_SIZE, TOTAL_FRAMES, TWO_SHOTS, make_test_video,
)


class TestDetectScenes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        root = Path(temporary.name)
        cls.video = make_test_video(root)
        cls.single_shot = make_test_video(root, two_shots=False)

    def test_detects_cut_at_frame_68(self):
        """The generated 121-frame clip has exactly two shots, cut at 68."""
        info = ffprobe(self.video)
        self.assertEqual(info["frames"], TOTAL_FRAMES)
        self.assertEqual((info["width"], info["height"]), (FRAME_SIZE, FRAME_SIZE))
        self.assertEqual(info["fps"], FRAME_RATE)
        scenes = detect_scenes(self.video)
        self.assertEqual(scenes, TWO_SHOTS)
        self.assertEqual(scenes[1]["start"], CUT_FRAME)

    def test_no_cut_returns_single_segment(self):
        """A constant shot covers every frame without an invented boundary."""
        self.assertEqual(
            detect_scenes(self.single_shot),
            [{"start": 0, "end": TOTAL_FRAMES - 1}],
        )

    def test_detects_scenes_returns_valid_ranges(self):
        """Inclusive ranges are contiguous and cover all 121 frames."""
        scenes = detect_scenes(self.video)
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0]["start"], 0)
        self.assertEqual(scenes[-1]["end"], TOTAL_FRAMES - 1)
        self.assertEqual(sum(seg["end"] - seg["start"] + 1 for seg in scenes), TOTAL_FRAMES)
        for seg in scenes:
            self.assertLess(seg["start"], seg["end"])
        for previous, current in zip(scenes, scenes[1:]):
            self.assertEqual(previous["end"] + 1, current["start"])


if __name__ == "__main__":
    unittest.main()
