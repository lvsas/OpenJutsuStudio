"""H3 is a direct, isolated two-pass graph, never a Ripple engine variant."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from h3_graphs import H3Models, build_h3_recast, h3_frames
from engines import ENGINES


class H3GraphTests(unittest.TestCase):
    def graph(self, **kwargs):
        return build_h3_recast("source.mp4", "reference.png", "Exact user text\n", **{"source_frames": 56, **kwargs})

    def test_frame_alignment_and_bad_counts(self):
        for n, expected in [(1, 5), (5, 5), (6, 22), (56, 56), (96, 107), (124, 124)]:
            self.assertEqual(h3_frames(n), expected)
        for n in (0, -1, True, 1.5, 3601):
            with self.subTest(n=n), self.assertRaises(ValueError):
                h3_frames(n)

    def test_direct_h3_preserves_prompt_and_source_references(self):
        g = self.graph(source_frames=96)
        self.assertEqual(g["136"]["inputs"]["prompt"], "Exact user text\n")
        self.assertEqual(g["136"]["inputs"]["length"], 107)
        self.assertEqual(g["155"]["inputs"]["frame_load_cap"], 96)
        self.assertEqual(g["136"]["inputs"]["ref_images.ref_image_0"], ["137", 0])
        self.assertEqual(g["136"]["inputs"]["ref_videos.ref_video_0"], ["161", 0])
        self.assertFalse(any(n["class_type"] == "MiniMaxH3AddGuide" for n in g.values()))
        self.assertFalse(any("ripple" in str(n).lower() or "flux" in str(n).lower() for n in g.values()))
        self.assertEqual(set(ENGINES), {"ltx25-ripple"})

    def test_sources_and_presets_are_not_tied_to_one_fixture(self):
        for frames in (14, 73, 217):
            for w, h in ((288, 512), (512, 288), (384, 384)):
                with self.subTest(frames=frames, width=w, height=h):
                    g = self.graph(source_frames=frames, width=w, height=h,
                                   output_width=w * 2, output_height=h * 2)
                    self.assertEqual(g["155"]["inputs"]["frame_load_cap"], frames)
                    self.assertEqual(g["136"]["inputs"]["length"], h3_frames(frames))
                    self.assertEqual(g["136"]["inputs"]["width"], w)
                    self.assertEqual(g["136"]["inputs"]["height"], h)
                    self.assertEqual(g["169"]["inputs"]["mode.width"], w * 2)
                    self.assertEqual(g["169"]["inputs"]["mode.height"], h * 2)
        with self.assertRaises(TypeError):
            build_h3_recast("s.mp4", "r.png", "Edit")

    def test_silent_source_has_no_missing_audio_connections(self):
        g = self.graph(source_audio=False)
        self.assertNotIn("ref_video_audios.ref_video_audio_0", g["136"]["inputs"])
        self.assertNotIn("audio", g["156"]["inputs"])
        self.assertNotIn("VAEDecodeAudio", [n["class_type"] for n in g.values()])
        with self.assertRaises(ValueError):
            self.graph(source_audio="false")

    def test_generic_guide_does_not_imply_temporal_pin(self):
        g = self.graph(guide_image="derived.png")
        self.assertEqual(g["136"]["inputs"]["ref_images.ref_image_1"], ["201", 0])
        self.assertEqual(g["126"]["inputs"]["conditioning"], ["136", 0])
        self.assertEqual(g["176"]["inputs"]["conditioning"], ["136", 0])

    def test_timed_guide_reaches_both_passes_with_matching_latents(self):
        g = self.graph(guide_image="derived.png", guide_frame=24)
        self.assertEqual(g["202"]["inputs"]["latent"], ["136", 1])
        self.assertEqual(g["203"]["inputs"]["latent"], ["171", 0])
        for gid, guider in [("202", "126"), ("203", "176")]:
            self.assertEqual(g[gid]["inputs"]["frame_idx"], 24)
            self.assertEqual(g[gid]["inputs"]["image"], ["201", 0])
            self.assertEqual(g[guider]["inputs"]["conditioning"], [gid, 0])

    def test_links_are_internal_and_calls_do_not_mutate_each_other(self):
        first = self.graph(guide_image="a.png", guide_frame=0)
        second = self.graph()
        self.assertNotIn("201", second)
        for g in (first, second):
            for node in g.values():
                for value in node["inputs"].values():
                    if isinstance(value, list):
                        self.assertIn(value[0], g)

    def test_explicit_model_overrides_and_asset_objects(self):
        asset = {"__type": "core/ASSET", "info": {"file_path": "source.mp4"}}
        g = build_h3_recast(asset, "r.png", "x", source_frames=56, models=H3Models(unet="custom.safetensors"))
        self.assertEqual(g["155"]["inputs"]["video"], asset)
        self.assertEqual(g["127"]["inputs"]["unet_name"], "custom.safetensors")

    def test_invalid_controls_fail_before_submission(self):
        for kw in [dict(width=513), dict(height=0), dict(steps=0), dict(split_step=6),
                   dict(seed=-1), dict(prompt=""), dict(guide_frame=0),
                   dict(guide_image="g.png", guide_frame=999), dict(guide_image="g.png", guide_frame=True),
                   dict(width=True), dict(steps=6.5)]:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                if "prompt" in kw:
                    build_h3_recast("s.mp4", "r.png", source_frames=56, **kw)
                else:
                    self.graph(**kw)
