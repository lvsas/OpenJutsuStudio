"""Character HTTP contracts without GPU, network or app.py integration."""
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import character_api  # noqa: E402
import core  # noqa: E402
from character_capsule import freeze_capsule  # noqa: E402
from character_recipe import make_recipe  # noqa: E402


def png(width=880, height=1184):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(
            ">I", zlib.crc32(kind + payload) & 0xffffffff)

    rows = (b"\x00" + b"\x00" * (width * 3)) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class CharacterAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / "media"
        self.media.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(core, "WORK", self.root).start()
        self.ready = MagicMock(return_value={"ready": True, "issues": [], "warnings": []})
        self.dispatch = MagicMock()
        app = FastAPI()
        app.include_router(character_api.create_router(lambda: self.media, self.ready, self.dispatch))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def submit(self, **overrides):
        payload = {"direction": "an original bowl-cut heavyweight beekeeper", "mode": "portrait",
                   "trend_id": "original", "selections": {"hair": "blunt bowl cut"},
                   "sampler_seed": 11, "upsampler_seed": 29, "upsampler": True}
        payload.update(overrides)
        return self.client.post("/api/characters/jobs", json=payload)

    def completed(self, *, caption="Studio photograph of an original beekeeper.", image=None):
        response = self.submit()
        self.assertEqual(response.status_code, 202, response.text)
        job, opts = self.dispatch.call_args.args
        folder = self.media / f"character-{job.id}"
        folder.mkdir(parents=True, exist_ok=True)
        image_path, caption_path = folder / "image.png", folder / "caption.txt"
        image_path.write_bytes(png() if image is None else image)
        caption_path.write_text(caption, encoding="utf-8")
        job.status, job.result = "done", str(image_path)
        job.meta.update(character_caption=str(caption_path))
        freeze_capsule(job, opts["recipe"], image_path, caption_path, self.media)
        job.save()
        return job

    def test_omitted_upsampler_keeps_exact_wording_by_default(self):
        response = self.client.post("/api/characters/jobs", json={"direction": "an adult with enormous geometric hair"})
        self.assertEqual(response.status_code, 202, response.text)
        recipe = self.dispatch.call_args.args[1]["recipe"]
        self.assertIs(recipe["upsampler"], False)

    def test_character_jobs_are_queued_with_a_frozen_recipe_and_own_namespace(self):
        response = self.submit()
        self.assertEqual(response.status_code, 202, response.text)
        job, opts = self.dispatch.call_args.args
        self.assertEqual(job.engine, "flux3-klein-character")
        self.assertEqual(job.status, "queued")
        self.assertEqual(opts["recipe"], job.meta["character_recipe"])
        self.assertEqual(opts["recipe"]["selections"]["hair"], "blunt bowl cut")
        self.assertEqual(Path(opts["media_dir"]), self.media)
        self.assertNotIn(str(self.root), response.text)

    def test_two_submissions_produce_independent_jobs_without_blocking(self):
        first = self.submit()
        second = self.submit(direction="an original chrome accordionist")
        self.assertEqual((first.status_code, second.status_code), (202, 202))
        ids = [call.args[0].id for call in self.dispatch.call_args_list]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        recipes = [call.args[1]["recipe"] for call in self.dispatch.call_args_list]
        self.assertEqual(recipes[0]["raw_direction"], "an original bowl-cut heavyweight beekeeper")
        self.assertEqual(recipes[1]["raw_direction"], "an original chrome accordionist")
        self.assertNotEqual(recipes[0]["graph_sha256"], recipes[1]["graph_sha256"])

    def test_invalid_or_unready_requests_never_dispatch(self):
        self.assertEqual(self.submit(mode="square").status_code, 422)
        self.assertEqual(self.submit(direction="   ").status_code, 422)
        self.assertEqual(self.submit(direction="a character sheet of a locksmith").status_code, 422)
        self.assertEqual(self.submit(selections={"unknown": "x"}).status_code, 422)
        self.assertEqual(self.submit(selections={"hair": "relative/secret.txt"}).status_code, 422)
        self.assertEqual(self.submit(sampler_seed=-1).status_code, 422)
        self.assertEqual(self.submit(upsampler="yes").status_code, 422)
        self.dispatch.assert_not_called()
        self.ready.return_value = {"ready": False, "issues": ["FLUX 3 weights missing"]}
        blocked = self.submit()
        self.assertEqual(blocked.status_code, 503)
        self.assertIn("FLUX 3 weights missing", blocked.text)
        self.dispatch.assert_not_called()

    def test_direction_origin_is_frozen_and_invalid_values_never_dispatch(self):
        generated = self.submit(direction_origin="generated")
        self.assertEqual(generated.status_code, 202, generated.text)
        recipe = self.dispatch.call_args.args[1]["recipe"]
        self.assertEqual(recipe["direction_origin"], "generated")
        self.assertIn("no hand-held or carried props", recipe["resolved_request"])
        self.dispatch.reset_mock()
        invalid = self.submit(direction_origin="system")
        self.assertEqual(invalid.status_code, 422)
        self.dispatch.assert_not_called()
        self.ready.return_value = {"ready": False, "issues": ["offline"]}
        invalid_while_offline = self.submit(direction_origin="system")
        self.assertEqual(invalid_while_offline.status_code, 422)
        self.assertIn("direction origin", invalid_while_offline.text)
        self.dispatch.assert_not_called()

    def test_dispatch_failure_is_terminal_and_reported(self):
        self.dispatch.side_effect = RuntimeError("executor unavailable")
        response = self.submit()
        self.assertEqual(response.status_code, 503)
        saved = core.Job.all()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].status, "error")
        self.assertIsNotNone(saved[0].finished)

    def test_result_routes_serve_typed_artifacts_only_when_done(self):
        response = self.submit()
        job_id = self.dispatch.call_args.args[0].id
        for route in ("image", "caption"):
            self.assertEqual(self.client.get(f"/api/characters/jobs/{job_id}/{route}").status_code, 409)
        self.assertEqual(self.client.get(f"/api/characters/jobs/{job_id}/capsule").status_code, 409)
        self.assertEqual(self.client.get("/api/characters/jobs/missing/image").status_code, 404)

        job = self.completed()
        image = self.client.get(f"/api/characters/jobs/{job.id}/image")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/png")
        caption = self.client.get(f"/api/characters/jobs/{job.id}/caption")
        self.assertEqual(caption.status_code, 200)
        self.assertEqual(caption.text, "Studio photograph of an original beekeeper.")
        self.assertNotIn(str(self.root), caption.text)
        capsule = self.client.get(f"/api/characters/jobs/{job.id}/capsule")
        self.assertEqual(capsule.status_code, 200, capsule.text)
        self.assertEqual(capsule.json()["resolved_caption"], "Studio photograph of an original beekeeper.")
        self.assertNotIn(str(self.root), capsule.text)
        status = self.client.get(f"/api/characters/jobs/{job.id}")
        self.assertEqual(status.json()["status"], "done")

    def test_tampered_capsule_and_changed_artifacts_block_replay(self):
        job = self.completed()
        tampered = dict(job.meta["character_capsule"])
        tampered["recipe"] = {**tampered["recipe"], "raw_direction": "changed"}
        job.meta["character_capsule"] = tampered
        job.save()
        self.assertEqual(self.client.get(f"/api/characters/jobs/{job.id}/capsule").status_code, 409)

        job = self.completed(caption="second caption")
        self.dispatch.reset_mock()
        replay = self.client.post(f"/api/characters/jobs/{job.id}/replay")
        self.assertEqual(replay.status_code, 202, replay.text)
        child, opts = self.dispatch.call_args.args
        self.assertNotEqual(child.id, job.id)
        self.assertEqual(opts["recipe"]["raw_direction"], job.meta["character_recipe"]["raw_direction"])
        self.assertEqual(opts["recipe"]["sampler_seed"], job.meta["character_recipe"]["sampler_seed"])
        self.assertEqual(opts["recipe"]["upsampler_seed"], job.meta["character_recipe"]["upsampler_seed"])
        self.assertEqual(child.meta["parent_job_id"], job.id)
        self.assertEqual(child.status, "queued")
        self.assertIsNone(child.result)

        (Path(job.meta["character_caption"])).write_text("mutated", encoding="utf-8")
        self.assertEqual(self.client.post(f"/api/characters/jobs/{job.id}/replay").status_code, 409)


if __name__ == "__main__":
    unittest.main()
