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
from output_media import (ASSET_ORDER, CHIP, DEFAULT_REEL_ENGINE, EYEBROW, HOOK, LABELS, LAYOUTS,
                          MICRO, SAFE_BOTTOM, STACKED, WIPE, build_comparison_reel, fonts,
                          reel_filters, restore_source_audio, wipe_filters, wipe_timing)
from reel_design import BASE, ENGINES, ensure_assets
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
                self.assertIn(EYEBROW, graph)
                self.assertIn(stack, graph)
                self.assertIn(accent, graph)
        # The brand is the application wordmark, in its two tones and its own display face.
        brand = reel_filters(1.0, "Sans")
        self.assertIn("text=OPEN:fontcolor=0xF7F5F1", brand)
        self.assertIn("text=GENJUTSU:fontcolor=0xD8FF3E", brand)
        # The two studios must not share a colour, and an unknown engine falls back.
        self.assertNotEqual(reel_filters(1.0, "Sans", "ltx25-ripple"),
                            reel_filters(1.0, "Sans", "minimax-h3"))
        self.assertEqual(reel_filters(1.0, "Sans", "unknown-engine"),
                         reel_filters(1.0, "Sans", DEFAULT_REEL_ENGINE))

    def test_the_reel_keeps_its_content_out_of_the_platform_bottom_zone(self):
        """Reels, Shorts and TikTok draw their caption and buttons over the bottom of the frame."""
        # The moving parts of each layout: overlays and bands, whose extent lives in the constants.
        bands = {"stacked": max(STACKED["panel"]["result_y"] + STACKED["panel"]["height"],
                                STACKED["micro"]["second_y"] + STACKED["micro"]["second_size"]),
                 "wipe": max(WIPE["band"]["y"] + WIPE["band"]["height"],
                             WIPE["micro"]["second_y"] + WIPE["micro"]["second_size"])}
        self.assertEqual(set(bands), set(LAYOUTS))
        for layout, graph in (("stacked", reel_filters(2.0, "Sans")),
                              ("wipe", wipe_filters(2.0, "Sans"))):
            with self.subTest(layout=layout):
                bottoms = [bands[layout]]
                for fragment in graph.split(","):
                    y = re.search(r"(?:^|:)y=(\d+)", fragment)
                    size = re.search(r"fontsize=(\d+)", fragment)
                    height = re.search(r"h=(\d+)", fragment)
                    if y and size:
                        bottoms.append(int(y.group(1)) + int(size.group(1)))
                    elif y and height:
                        bottoms.append(int(y.group(1)) + int(height.group(1)))
                self.assertTrue(len(bottoms) > 3, f"too few positioned elements in {layout}")
                self.assertLessEqual(max(bottoms), SAFE_BOTTOM,
                                     f"{layout} content would be covered by the platform interface")
        # The graphs must actually reuse those constants rather than a stray literal.
        self.assertIn(f"overlay={STACKED['panel']['x']}:{STACKED['panel']['result_y']}",
                      reel_filters(2.0, "Sans"))
        self.assertIn(f"overlay={WIPE['band']['x']}:{WIPE['band']['y']}",
                      wipe_filters(2.0, "Sans"))

    def test_the_wipe_sweeps_the_result_over_one_band(self):
        graph = wipe_filters(2.4, "Sans", "minimax-h3")
        self.assertIn(HOOK[0], graph)
        self.assertIn(HOOK[1], graph)
        self.assertIn("text=SOURCE", graph)
        self.assertIn("text=SWAP", graph)
        self.assertNotIn("RECAST", graph)
        self.assertIn("MiniMax H3 + Character Swap LoRA", graph)
        # A real wipe, not a slide: a growing alpha mask over a result that never moves.
        band = WIPE["band"]
        self.assertIn("alphamerge[revealed]", graph)
        # Both halves carry the rounded frame: leaving the source unmasked paints square
        # corners over the radius, which is invisible until you look at a corner pixel.
        mask_input = 2 + ASSET_ORDER.index("band_mask")
        self.assertIn(f"[src][{mask_input}:v]alphamerge[src_r]", graph)
        # The radius must survive the reveal: the two masks are applied one after the other
        # rather than replacing the alpha.
        self.assertIn("alphamerge[revealed]", graph)
        self.assertIn(f"[revealed][{mask_input}:v]alphamerge[revealed_rounded]", graph)
        # The edge travels inside the band, so the same mask clips it.
        inside_x_pattern = f"({band['width']}-(2*floor({band['width'] // 2}*max(0,min(1,"
        self.assertIn(f"overlay=x='{inside_x_pattern}", graph)
        self.assertIn(f"color=c=white:s={band['width']}x{band['height']}", graph)
        self.assertIn(f"color=c=0xFF4F2E:s=5x{band['height']}", graph)
        self.assertRegex(graph, rf"\[blank\]\[white\]overlay=x='\({band['width']}-"
                                 rf"\(2\*floor\({band['width'] // 2}\*max\(0,min\(1,")
        # drawbox cannot animate its position: such an expression silently draws nothing, so
        # no animated drawbox may creep back into this layout.
        self.assertNotIn("drawbox=x='", graph)
        self.assertNotIn("crop=", graph)
        # The second label waits for the result instead of announcing it early.
        hold, sweep = wipe_timing(2.4)
        self.assertIn(f"enable='gte(t,{round(hold + sweep, 3)})'", graph)

    @staticmethod
    def _size(path):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True).stdout.strip()
        return tuple(int(value) for value in out.split(","))

    @staticmethod
    def _pixel(path, x, y, width=1080):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        index = (y * width + x) * 3
        return raw[index], raw[index + 1], raw[index + 2]

    def test_the_static_design_artwork_is_generated_to_measure(self):
        """The look comes from the application's tokens, and the artwork follows them."""
        assets = ensure_assets(self.root / "assets", "ltx25-ripple", labels=LABELS,
                               label_ink=CHIP["ink"], label_size=CHIP["size"],
                               band=(WIPE["band"]["width"], WIPE["band"]["height"]))
        for name in ("background", "band_mask", "band_outline", "chip_source", "chip_swap"):
            self.assertTrue(Path(assets[name]).is_file(), f"{name} was not generated")
        self.assertEqual(self._size(assets["background"]), (1080, 1920))
        self.assertEqual(self._size(assets["band_mask"]),
                         (WIPE["band"]["width"], WIPE["band"]["height"]))
        # A chip hugs its text: its width comes from the measured ink, not from a guess.
        self.assertEqual(self._size(assets["chip_source"]),
                         (CHIP["ink"][0] + CHIP["pad"], CHIP["size"] + 26))
        # The ambient glow carries the studio's colour, so the two reels are not one image.
        for engine, palette in ENGINES.items():
            background = ensure_assets(self.root / f"assets-{engine}", engine,
                                       band=(2, 2))["background"]
            centre = self._pixel(background, int(1080 * 0.76), int(1920 * 0.10))
            corner = self._pixel(background, 30, 1890)
            self.assertNotEqual(centre, BASE["bg"], "the glow was not drawn at all")
            # body::before puts it at 76% across, 10% down; the far corner stays flat.
            self.assertGreater(sum(abs(c - b) for c, b in zip(centre, BASE["bg"])),
                               sum(abs(c - b) for c, b in zip(corner, BASE["bg"])),
                               f"{engine}: the glow is not where the stylesheet puts it")
            # And it leans towards the studio's own accent, not towards the other's.
            red, green = centre[0], centre[1]
            self.assertGreater(red if palette["accent"][0] > palette["accent"][1] else green,
                               green if palette["accent"][0] > palette["accent"][1] else red,
                               f"{engine}: the glow does not carry the studio colour")

    def test_wipe_timing_always_holds_sweeps_and_settles_inside_the_clip(self):
        for duration in (0.6, 1.0, 2.334, 5.0, 12.0):
            with self.subTest(duration=duration):
                hold, sweep = wipe_timing(duration)
                self.assertGreater(hold, 0.0)
                self.assertGreater(sweep, 0.0)
                self.assertLess(hold + sweep, duration, "the result would never be seen alone")

    def test_an_unknown_layout_is_refused_before_any_render(self):
        with self.assertRaises(ValueError):
            build_comparison_reel("missing.mp4", "missing.mp4", Path("out.mp4"), layout="diagonal")

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
