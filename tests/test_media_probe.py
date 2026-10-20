"""Real CPU media checks for supported containers and source audio."""
import json
from array import array
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from media import ffprobe
from output_media import (ASSET_ORDER, CHIP, DEFAULT_REEL_ENGINE, EYEBROW, HOOK, LABELS, LAYOUTS,
                          MICRO, SAFE_BOTTOM, STACKED, WIPE, build_comparison_reel, build_social_reel, fonts,
                          reel_filters, reel_timeline, restore_source_audio, social_reel_filters, validate_reel_media,
                          wipe_filters, wipe_label_timing, wipe_timing)
from reel_design import BASE, ENGINES, SOCIAL, ensure_assets
from scenes import detect_scenes


class MediaProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Keep generated artwork out of the shared production cache during concurrent work.
        assets = patch("output_media.REEL_ASSET_DIR", self.root / "reel-assets")
        assets.start()
        self.addCleanup(assets.stop)

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
        # A real wipe, not a slide: its moving boundary chooses source before the sweep and
        # result after it, then only the completed frame receives rounded alpha.
        band = WIPE["band"]
        mask_input = 2 + ASSET_ORDER.index("band_mask")
        self.assertIn("[src][resmarked]blend=all_expr='if(gte(X,", graph)
        self.assertIn(f"[transition][{mask_input}:v]alphamerge[transition_rounded]", graph)
        # The existing narrow edge travels inside the band while blend controls the actual reveal.
        inside_x_pattern = f"({band['width']}-(2*floor({band['width'] // 2}*max(0,min(1,"
        self.assertIn(f"overlay=x='{inside_x_pattern}", graph)
        self.assertIn(f"color=c=0xFF4F2E:s=5x{band['height']}", graph)
        # drawbox cannot animate its position: such an expression silently draws nothing, so
        # no animated drawbox may creep back into this layout.
        self.assertNotIn("drawbox=x='", graph)
        # Crop may cover a static ambient plate, but animated crop dimensions remain forbidden:
        # FFmpeg evaluates them once and silently breaks the intended reveal.
        self.assertNotIn("crop=w=", graph)
        self.assertNotIn("crop=iw", graph)
        # SOURCE exits before its chip crosses the wipe; SWAP appears only once its chip is
        # entirely within revealed result pixels.
        source_until, swap_from = wipe_label_timing(2.4)
        self.assertIn(f"enable='lt(t,{source_until})'", graph)
        self.assertIn(f"enable='gte(t,{swap_from})'", graph)

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
        self.assertEqual(self._size(assets["passport_ticket"]), (840, 190))
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

    def test_social_candidate_render_preserves_frames_and_truthful_states(self):
        source, result, reel = [self.root / name for name in ("source.mp4", "result.mp4", "social.mp4")]
        for path, colour in ((source, "0xD02030"), (result, "0x2050D0")):
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            f"color=c={colour}:size=64x64:rate=24", "-frames:v", "29",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
        with patch("output_media.ensure_assets", wraps=ensure_assets) as artwork:
            build_social_reel(source, result, reel)
        artwork_dir = Path(artwork.call_args.args[0])
        self.assertEqual(artwork_dir.parent, reel.parent)
        self.assertTrue(artwork_dir.name.startswith(".reel-artwork-"))
        self.assertFalse(artwork_dir.exists(), "Private artwork must be cleaned after export")
        info = ffprobe(reel)
        self.assertEqual(info["frames"], 29)
        self.assertAlmostEqual(info["duration"], 29 / 24, places=6)
        self.assertEqual(info["fps"], 24)
        self.assertEqual((self._size(reel)), (1080, 1920))
        band = WIPE["band"]
        x, y = band["x"] + band["width"] // 2, band["y"] + band["height"] // 2
        source_pixels = self._frame_region(source, 0, 20, 20)
        result_pixels = self._frame_region(result, 0, 20, 20)
        first = self._frame_region(reel, 0, x, y)
        last = self._frame_region(reel, info["frames"] - 1, x, y)
        self.assertLess(self._mae(first, source_pixels), self._mae(first, result_pixels))
        self.assertLess(self._mae(last, result_pixels), self._mae(last, source_pixels))
        first_ambient = self._frame_region(reel, 0, 1000, 1700)
        last_ambient = self._frame_region(reel, info["frames"] - 1, 1000, 1700)
        self.assertGreater(first_ambient[0] - first_ambient[2], 40,
                           "the ambient plate must begin on the source take")
        self.assertGreater(last_ambient[2] - last_ambient[0], 40,
                           "the ambient plate must settle on the swapped result")
        timeline = reel_timeline(info["duration"], info["fps"], info["frames"])
        mid_frame = round((timeline["capture_end"] + timeline["recast_duration"] / 2)
                          * timeline["fps"])
        mid_left = self._frame_region(reel, mid_frame, 100, 1700)
        mid_right = self._frame_region(reel, mid_frame, 950, 1700)
        self.assertGreater(mid_left[0] - mid_left[2], 25,
                           "the ambient sweep should retain source on the left mid-wipe")
        self.assertGreater(mid_right[2] - mid_right[0], 25,
                           "the ambient sweep should reveal result on the right mid-wipe")

        # Check actual sharp pixels on both sides, not just the ambient or a filter label.
        for offset, expected, other in ((150, source_pixels, result_pixels),
                                        (band["width"] - 150, result_pixels, source_pixels)):
            pixels = self._frame_region(reel, mid_frame, band["x"] + offset, y)
            self.assertLess(self._mae(pixels, expected), self._mae(pixels, other))

        # Preserve the accepted narrow central wipe line, including its full-height geometry.
        height = 200
        pixels = self._frame_region(reel, mid_frame, band["x"], band["y"] + 150,
                                    width=band["width"], height=height)
        accent = ENGINES[DEFAULT_REEL_ENGINE]["accent"]
        columns = [x for x in range(band["width"])
                   if sum(all(abs(pixels[(row * band["width"] + x) * 3 + c] - accent[c]) < 20
                              for c in range(3)) for row in range(height)) >= height * 0.95]
        progress = ((mid_frame - timeline["capture_end_frame"]) /
                    (timeline["recast_end_frame"] - timeline["capture_end_frame"]))
        edge = band["width"] - 2 * int(band["width"] // 2 * progress)
        self.assertGreaterEqual(len(columns), 2, "the full-height wipe edge disappeared")
        self.assertLessEqual(len(columns), WIPE["edge"] + 2)
        self.assertLessEqual(abs(columns[0] - edge), 2)

        # Measure title ink: subtle vertical lift only during reveal, never hidden at rest.
        swap = SOCIAL["swap"]
        top, height = swap["y"] - swap["reveal_lift"] - 4, swap["size"] + 20
        bounds = {}
        for frame in (0, timeline["capture_end_frame"] - 1, mid_frame,
                      timeline["collect_start_frame"], info["frames"] - 1):
            pixels = self._frame_region(reel, frame, 0, top, width=1080, height=height)
            ink = [(i // 3) // 1080 for i in range(0, len(pixels), 3)
                   if all(abs(pixels[i + c] - accent[c]) < 20 for c in range(3))]
            self.assertGreater(len(ink), 1000, f"SWAP must remain visible at frame {frame}")
            bounds[frame] = (min(ink), max(ink))
        for frame in (timeline["capture_end_frame"] - 1, timeline["collect_start_frame"],
                      info["frames"] - 1):
            self.assertEqual(bounds[frame], bounds[0], "the title must not move at rest")
        self.assertAlmostEqual(bounds[0][0] - bounds[mid_frame][0], swap["reveal_lift"], delta=1)
        self.assertGreaterEqual(top + bounds[mid_frame][0], swap["y"] - swap["reveal_lift"])
        self.assertLess(top + bounds[0][1], SOCIAL["subtitle"]["y"])

    def test_social_portrait_background_tracks_real_result_time_and_full_audio(self):
        """A changing take catches xfade's old hold-sized lag and source-only hero blur."""
        source, result, reel = [self.root / name for name in ("source.mp4", "result.mp4", "social.mp4")]
        frames, fps = 29, 24
        duration = frames / fps
        for path, colour, tone in ((source, "r='160+2*N':g=30:b=40", 330),
                                   (result, "r='15+4*N':g='25+4*N':b='100+5*N'", 660)):
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            f"color=size=64x96:rate={fps},format=rgb24,geq={colour}",
                            "-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000",
                            "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-movie_timescale", "48000", str(path)],
                           capture_output=True, check=True)
        build_social_reel(source, result, reel)
        info = ffprobe(reel)
        self.assertEqual((info["frames"], info["fps"]), (frames, fps))
        self.assertAlmostEqual(info["duration"], duration, places=6)
        timeline = reel_timeline(duration, fps, frames)
        band = WIPE["band"]
        # Independent reference plates: grade the real input at the SAME frame. Solid temporal
        # ramps survive scale/blur and make a lagged result measurably different, unlike testsrc
        # regions which can accidentally be unchanged from frame to frame.
        ambient_grade = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                         "gblur=sigma=48,eq=brightness=-0.18:saturation=0.58:contrast=1.04,"
                         "format=yuv444p,drawbox=color=0x101014@0.18:t=fill")
        cover_grade = (f"scale={band['width']}:{band['height']}:force_original_aspect_ratio=increase,"
                       f"crop={band['width']}:{band['height']},gblur=sigma=28,"
                       "eq=brightness=-0.12:saturation=0.58:contrast=1.03")
        mid = (timeline["capture_end_frame"] + timeline["recast_end_frame"]) // 2
        settled = timeline["collect_start_frame"] + 1
        for frame, plate in ((0, source), (mid, source), (mid, result),
                             (settled, result), (frames - 1, result)):
            right = plate == result and frame == mid
            ambient_x = 1000 if right else 50
            actual = self._frame_region(reel, frame, ambient_x, 1700)
            expected = self._frame_region(plate, frame, ambient_x, 1700, prefix=ambient_grade)
            self.assertLess(self._mae(actual, expected), 5,
                            f"ambient must follow {plate.name} frame {frame}, not frame t-hold")
            # Portrait filler is outside the sharp image's horizontal footprint on each side.
            cover_x = band["width"] - 100 if right else 80
            actual_cover = self._frame_region(reel, frame, band["x"] + cover_x,
                                               band["y"] + band["height"] // 2)
            expected_cover = self._frame_region(plate, frame, cover_x, band["height"] // 2,
                                                 prefix=cover_grade)
            self.assertLess(self._mae(actual_cover, expected_cover), 5,
                            f"portrait filler must follow {plate.name} frame {frame}")
            sharp_x = band["width"] // 2 + (100 if right else -100)
            sharp = self._frame_region(reel, frame, band["x"] + sharp_x,
                                       band["y"] + band["height"] // 2)
            original = self._frame_region(plate, frame, 20, 40)
            self.assertLess(self._mae(sharp, original), 5,
                            f"sharp hero must preserve {plate.name} frame {frame}")
            if plate == result:
                delayed = self._frame_region(result, frame - timeline["capture_end_frame"],
                                             ambient_x, 1700, prefix=ambient_grade)
                self.assertGreater(self._mae(actual, delayed), self._mae(actual, expected) + 5,
                                   "fixture must distinguish the old xfade timing bug")

        streams = json.loads(subprocess.run([
            "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(reel)],
            text=True, capture_output=True, check=True).stdout)["streams"]
        video = next(s for s in streams if s["codec_type"] == "video")
        audio = next(s for s in streams if s["codec_type"] == "audio")
        self.assertEqual((video["codec_name"], video["pix_fmt"]), ("h264", "yuv420p"))
        self.assertEqual(audio["codec_name"], "aac")
        self.assertAlmostEqual(float(audio["duration"]), duration, delta=1 / 48000)
        # Compare decoded tail audio to both inputs: result audio (not source) survives in sync
        # through the final take. AAC padding is excluded from the sample-accurate budget.
        pcm = {}
        samples = round(duration * 48000)
        for path in (source, result, reel):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
                                  "-af", f"atrim=end_sample={samples}", "-f", "f32le", "-"],
                                 capture_output=True, check=True).stdout
            pcm[path] = array("f", raw)
        self.assertEqual(len(pcm[reel]), samples)
        tail = pcm[reel][-4800:]
        self.assertLess(self._mae(tail, pcm[result][-4800:]), 0.005)
        self.assertGreater(self._mae(tail, pcm[source][-4800:]), 0.05)

    def test_social_candidate_blends_source_ambient_and_delayed_passport(self):
        timeline = reel_timeline(73 / 24, 24, 73)
        graph = social_reel_filters(73 / 24, fonts(), inputs={
            "band_mask": 3, "band_outline": 4, "passport_ticket": 7,
        }, fps=24, timeline=timeline)
        self.assertIn("[0:v]scale=1080:1920", graph)
        self.assertIn("[1:v]trim=start_frame=16,scale=1080:1920", graph)
        self.assertIn("[source_ambient][result_ambient]xfade=transition=smoothleft", graph)
        self.assertIn("gblur=sigma=48", graph)
        self.assertIn("[0:v]scale=992:558", graph)
        self.assertIn("[src][resmarked]blend=", graph)
        self.assertIn("overlay=120:y=", graph)
        self.assertIn("enable='gte(t,1.125000)'", graph)
        self.assertIn(r"text=REALITY\,", graph)
        self.assertIn("text=SWAP.", graph)
        self.assertIn(EYEBROW, graph)
        self.assertIn("text=YOUR CHARACTER. YOUR MOMENT.", graph)
        for unwanted in ("RECAST", "OG / 01", "TAKE PASSPORT"):
            self.assertNotIn(unwanted, graph)
        self.assertIn("[res_cover][res_sharp]overlay=0:0[res]", graph)
        self.assertNotIn("src_cover_b", graph)
        # The content and Passport text remain within the social safe-area bottom.
        self.assertLessEqual(SOCIAL["passport"]["y"] + SOCIAL["passport"]["height"], SAFE_BOTTOM)
        self.assertNotIn("drawbox=x='", graph)

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

    @staticmethod
    def _frame_region(path, frame, x, y, width=24, height=24, prefix=""):
        """Decode a small frame region without materialising a portrait reel in memory."""
        # trim selects the requested decoded frame without materialising the reel.
        filters = f"trim=start_frame={frame}:end_frame={frame + 1},"
        filters += (prefix + "," if prefix else "") + f"crop={width}:{height}:{x}:{y}"
        pixels = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", filters,
                                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                capture_output=True, check=True).stdout
        if len(pixels) != width * height * 3:
            raise AssertionError(f"Missing/rounded RGB region: {path} frame {frame}, {width}x{height}")
        return pixels

    @staticmethod
    def _mae(left, right):
        return sum(abs(a - b) for a, b in zip(left, right)) / len(left)

    def test_reel_timeline_adapts_to_duration_and_real_frame_rate(self):
        cases = (
            (1.2, 24, 29, "compact"),
            (73 / 24, 24, 73, "standard"),
            (8.0, 24, 192, "standard"),
            (20.0, 30, 600, "extended"),
        )
        for duration, fps, frames, mode in cases:
            with self.subTest(duration=duration, fps=fps):
                timeline = reel_timeline(duration, fps, frames)
                self.assertEqual(timeline["mode"], mode)
                self.assertEqual(timeline["frame_count"], frames)
                self.assertEqual(timeline["capture_start_frame"], 0)
                self.assertLess(timeline["capture_end_frame"], timeline["recast_end_frame"])
                self.assertLess(timeline["recast_end_frame"], frames)
                self.assertEqual(timeline["collect_start_frame"], timeline["recast_end_frame"])
                self.assertGreaterEqual(frames - timeline["collect_start_frame"], 1)
        # The accepted V2 reveal cadence is an anchor, not a fixed timer: interpolate by actual
        # duration for intermediate and longer takes while retaining frame alignment.
        ltx = reel_timeline(73 / 24, 24, 73)
        h3 = reel_timeline(8.0, 24, 192)
        self.assertEqual((ltx["capture_end_frame"], ltx["recast_end_frame"]), (16, 27))
        self.assertEqual((h3["capture_end_frame"], h3["recast_end_frame"]), (18, 29))
        medium = reel_timeline(5.0, 30, 150)
        self.assertGreater(medium["capture_end"], ltx["capture_end"])
        self.assertLess(medium["capture_end"], h3["capture_end"])
        self.assertAlmostEqual(medium["recast_duration"], 0.45, delta=1 / 30)

    def test_reel_media_validation_rejects_unsynchronised_source(self):
        source, result = self.root / "source.mp4", self.root / "result.mp4"
        for path, duration in ((source, 0.5), (result, 1.0)):
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            f"color=size=64x64:rate=24:duration={duration}", "-c:v", "libx264", str(path)],
                           check=True)
        with self.assertRaisesRegex(ValueError, "source.*shorter"):
            validate_reel_media(source, result)

    def test_wipe_is_source_first_result_last_with_exact_ltx_timing(self):
        """A 73-frame LTX-shaped fixture catches the old 74th frame and label lie."""
        source, result, reel = [self.root / name for name in ("source.mp4", "result.mp4", "wipe.mp4")]
        for path, colour, tone in ((source, "0xE02020", "330"), (result, "0x2050E0", "660")):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"color=c={colour}:size=64x64:rate=24", "-f", "lavfi", "-i",
                            f"sine=frequency={tone}:sample_rate=48000", "-frames:v", "73",
                            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            str(path)], check=True)
        result_info = ffprobe(result)
        self.assertEqual((result_info["frames"], result_info["fps"]), (73, 24.0))
        hold, sweep = wipe_timing(result_info["duration"])
        self.assertEqual(hold, 0.4, "the source first beat must end by 0.4 seconds")
        source_until, swap_from = wipe_label_timing(result_info["duration"])
        graph = wipe_filters(result_info["duration"], "Sans")
        self.assertIn(f"enable='lt(t,{source_until})'", graph)
        self.assertIn(f"enable='gte(t,{swap_from})'", graph)

        build_comparison_reel(source, result, reel, layout="wipe")
        reel_info = ffprobe(reel)
        self.assertEqual(reel_info["frames"], result_info["frames"],
                         "the reel must not synthesize a 74th LTX frame")
        self.assertAlmostEqual(reel_info["duration"], result_info["duration"], places=3)
        band = WIPE["band"]
        x, y = band["x"] + band["width"] // 2, band["y"] + band["height"] // 2
        source_pixels = self._frame_region(source, 0, 20, 20)
        result_pixels = self._frame_region(result, 0, 20, 20)
        pre_pixels = self._frame_region(reel, 0, x, y)
        post_pixels = self._frame_region(reel, reel_info["frames"] - 1, x, y)
        self.assertLess(self._mae(pre_pixels, source_pixels), self._mae(pre_pixels, result_pixels),
                        "SOURCE's first beat must use actual source pixels")
        self.assertLess(self._mae(post_pixels, result_pixels), self._mae(post_pixels, source_pixels),
                        "the held end state must use actual result pixels")

        streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json",
                                             str(reel)], text=True, capture_output=True, check=True).stdout)["streams"]
        video = next(stream for stream in streams if stream["codec_type"] == "video")
        audio = next(stream for stream in streams if stream["codec_type"] == "audio")
        self.assertEqual((video["codec_name"], video["pix_fmt"]), ("h264", "yuv420p"))
        self.assertEqual(audio["codec_name"], "aac")
        self.assertLess(reel.read_bytes().find(b"moov"), reel.read_bytes().find(b"mdat"),
                        "faststart must put MP4 metadata before media data")
