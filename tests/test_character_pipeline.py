"""Character worker lifecycle: frozen recipe -> exact SDK artifacts -> capsule -> done."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core import Job  # noqa: E402
from character_recipe import ENGINE, make_recipe  # noqa: E402
from character_pipeline import run_character_pipeline  # noqa: E402


def png(width=880, height=1184):
    import struct
    import zlib

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = (b"\x00" + b"\x00" * (width * 3)) * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class CharacterPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.media = Path(self.tmp.name) / "media"
        self.recipe = make_recipe(
            job_id="character_worker_1", direction="an original beekeeper", mode="portrait",
            trend_id="original", selections={"hair": "blunt bowl cut"}, sampler_seed=10,
            upsampler_seed=20, upsampler=True)
        self.job = Job(id="character_worker_1", engine=ENGINE, meta={"character_recipe": self.recipe})

    def _artifacts(self, folder, *, image_bytes=None, caption="Studio photograph of an original beekeeper."):
        folder.mkdir(parents=True)
        image, text = folder / "image.png", folder / "caption.txt"
        image.write_bytes(png() if image_bytes is None else image_bytes)
        text.write_text(caption, encoding="utf-8")
        return {"image": image, "caption": text}

    def test_worker_freezes_recipe_and_capsule_before_marking_done(self):
        client = MagicMock()
        states = []
        with patch("character_pipeline.make_client", return_value=client), \
             patch("character_pipeline._run_graph_artifacts", side_effect=lambda c, g, r, f, on_progress: (
                 states.append((g, r)), self._artifacts(f))[1]):
            run_character_pipeline(self.job, {"recipe": self.recipe, "media_dir": self.media})

        self.assertEqual(self.job.status, "done")
        self.assertEqual(self.job.step, "done")
        self.assertEqual(self.job.progress, 1.0)
        self.assertTrue(Path(self.job.result).is_file())
        self.assertEqual(Path(self.job.meta["character_caption"]).read_text(),
                         "Studio photograph of an original beekeeper.")
        self.assertEqual(self.job.meta["character_capsule"]["recipe"], self.recipe)
        self.assertEqual(states[0][0], self.recipe["graph_template"])
        self.assertEqual(states[0][1], {"image": ("9", {".png"}),
                                        "caption": ("character_caption", {".txt"})})
        client.close.assert_called_once()

    def test_worker_refuses_a_different_valid_recipe_than_the_queued_one(self):
        replacement = make_recipe(
            job_id="character_worker_1", direction="a different valid original locksmith", mode="portrait",
            trend_id="original", selections={}, sampler_seed=10, upsampler_seed=20, upsampler=True)
        client = MagicMock()
        with patch("character_pipeline.make_client", return_value=client):
            run_character_pipeline(self.job, {"recipe": replacement, "media_dir": self.media})
        self.assertEqual(self.job.status, "error")
        self.assertIn("recipe differs", self.job.error)
        self.assertEqual(self.job.meta["character_recipe"], self.recipe)
        client.close.assert_not_called()

    def test_missing_sdk_artifact_never_yields_done_or_capsule(self):
        client = MagicMock()
        with patch("character_pipeline.make_client", return_value=client), \
             patch("character_pipeline._run_graph_artifacts", side_effect=RuntimeError("Missing output")):
            run_character_pipeline(self.job, {"recipe": self.recipe, "media_dir": self.media})
        self.assertEqual(self.job.status, "error")
        self.assertIsNone(self.job.result)
        self.assertNotIn("character_capsule", self.job.meta)
        client.close.assert_called_once()

    def test_invalid_png_or_caption_cleans_published_artifacts_and_fails(self):
        client = MagicMock()
        with patch("character_pipeline.make_client", return_value=client), \
             patch("character_pipeline._run_graph_artifacts", side_effect=lambda c, g, r, f, on_progress: (
                 self._artifacts(f, image_bytes=b"not-png"))):
            run_character_pipeline(self.job, {"recipe": self.recipe, "media_dir": self.media})
        self.assertEqual(self.job.status, "error")
        self.assertFalse((self.media / "character-character_worker_1").exists())
        self.assertNotIn("character_caption", self.job.meta)
        self.assertNotIn("character_capsule", self.job.meta)


if __name__ == "__main__":
    unittest.main()
