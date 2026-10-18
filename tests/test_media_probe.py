"""Real CPU media checks for supported containers and source audio."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from media import ffprobe
from output_media import (DEFAULT_REEL_ENGINE, PANELS, SAFE_BOTTOM, build_comparison_reel,
                          reel_filters, restore_source_audio)
from scenes import detect_scenes


class MediaProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_webm_count_is_measured_without_nb_frames(self):
        path = self.root / "input.webm"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=64x64:rate=24", "-frames:v", "17",
                        "-c:v", "libvpx-vp9", str(path)], check=True)
        info = ffprobe(path)
        self.assertEqual(info["frames"], 17)
        self.assertGreater(info["duration"], 0)
        self.assertEqual(detect_scenes(path)[-1]["end"], 16)

    def test_short_audio_does_not_truncate_edited_video(self):
        video, source, result = [self.root / name for name in ("edited.mp4", "source.mp4", "final.mp4")]
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "color=size=64x64:rate=24:duration=1", "-c:v", "libx264", str(video)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=0.4", "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", str(source)], check=True)
        restore_source_audio(str(video), str(source), result)
        self.assertEqual(ffprobe(result)["frames"], 24)
        data = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(result)],
                              text=True, capture_output=True, check=True)
        self.assertIn("audio", [s["codec_type"] for s in json.loads(data.stdout)["streams"]])

    def test_silent_source_is_supported(self):
        path, result = self.root / "silent.mp4", self.root / "final.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "color=size=64x64:rate=24:duration=1", "-c:v", "libx264", str(path)], check=True)
        restore_source_audio(str(path), str(path), result)
        self.assertEqual(ffprobe(result)["frames"], 24)

    def test_the_reel_labels_the_swap_and_carries_the_studio_colour(self):
        for engine, accent, stack in (("ltx25-ripple", "0xD8FF3E", "FLUX 2 Klein + LTX 2.5 + Ripple"),
                                      ("minimax-h3", "0xFF4F2E", "MiniMax H3 + Character Swap LoRA")):
            with self.subTest(engine=engine):
                graph = reel_filters(1.0, "Sans", engine)
                self.assertIn("text=SWAP", graph)
                self.assertNotIn("RECAST", graph)
                self.assertIn("text=SOURCE", graph)
                self.assertIn("CHARACTER SWAP", graph.upper())
                self.assertIn(stack, graph)
                self.assertIn(accent, graph)
        # The brand is the application wordmark, in its two tones.
        brand = reel_filters(1.0, "Sans")
        self.assertIn("text=OPEN:fontcolor=white", brand)
        self.assertIn("text=GENJUTSU:fontcolor=0xD8FF3E", brand)
        # The two studios must not share a colour, and an unknown engine falls back.
        self.assertNotEqual(reel_filters(1.0, "Sans", "ltx25-ripple"),
                            reel_filters(1.0, "Sans", "minimax-h3"))
        self.assertEqual(reel_filters(1.0, "Sans", "unknown-engine"),
                         reel_filters(1.0, "Sans", DEFAULT_REEL_ENGINE))

    def test_the_reel_keeps_its_content_out_of_the_platform_bottom_zone(self):
        """Reels, Shorts and TikTok draw their caption and buttons over the bottom of the frame."""
        bottoms = []
        for fragment in reel_filters(2.0, "Sans").split(","):
            overlay = re.search(r"overlay=\d+:(\d+)", fragment)
            y = re.search(r"(?:^|:)y=(\d+)", fragment)
            size = re.search(r"fontsize=(\d+)", fragment)
            height = re.search(r"h=(\d+)", fragment)
            if overlay:
                bottoms.append(int(overlay.group(1)) + PANELS["height"])
            elif y and size:
                bottoms.append(int(y.group(1)) + int(size.group(1)))
            elif y and height:
                bottoms.append(int(y.group(1)) + int(height.group(1)))
        self.assertTrue(bottoms, "no positioned element was found to check")
        self.assertLessEqual(max(bottoms), SAFE_BOTTOM,
                             "reel content would be covered by the platform interface")

    def test_comparison_reel_is_portrait_h264_with_result_duration(self):
        source, result, reel = [self.root / name for name in ("source.mp4", "result.mp4", "reel.mp4")]
        for path, color in ((source, "navy"), (result, "teal")):
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            f"color=c={color}:size=64x64:rate=24:duration=1", "-c:v", "libx264", str(path)],
                           check=True)
        build_comparison_reel(source, result, reel)
        info = ffprobe(reel)
        self.assertEqual((info["width"], info["height"]), (1080, 1920))
        self.assertEqual(info["fps"], ffprobe(result)["fps"])
        self.assertLessEqual(abs(info["frames"] - ffprobe(result)["frames"]), 1)
        streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(reel)],
                                             text=True, capture_output=True, check=True).stdout)["streams"]
        self.assertEqual(next(stream["codec_name"] for stream in streams if stream["codec_type"] == "video"), "h264")
