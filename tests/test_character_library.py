"""Durable Character membership: isolated jobs/media, never real renders or library writes."""
import concurrent.futures
import json
import multiprocessing
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_character_api as fixtures
import core


def _save_member(root, media, job_id):
    import character_library
    core.WORK = Path(root)
    character_library.CharacterLibrary(lambda: Path(media)).save(job_id, {})


class CharacterLibraryTests(unittest.TestCase):
    root: Path
    media: Path
    client: fixtures.TestClient
    setUp = fixtures.CharacterAPITests.setUp
    submit = fixtures.CharacterAPITests.submit
    completed = fixtures.CharacterAPITests.completed
    @property
    def index(self):
        return self.root / "characters" / "library.json"

    def save_member(self, job, payload=None):
        return self.client.post(f"/api/characters/library/{job.id}", json=payload or {})

    def members(self):
        response = self.client.get("/api/characters/library")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["characters"]

    def test_explicit_save_survives_router_restart_and_delete_preserves_every_asset(self):
        job = self.completed()
        self.assertEqual(self.members(), [], "generation is not library membership")
        original = job.path.read_bytes()
        result = self.save_member(job, {"name": "My <original> person"})
        self.assertEqual(result.status_code, 200, result.text)
        entry = self.members()[0]
        self.assertEqual(entry["job_id"], job.id)
        self.assertEqual(entry["name"], "My <original> person")
        self.assertEqual(entry["image_url"], f"/api/characters/jobs/{job.id}/image")
        self.assertNotIn(str(self.root), json.dumps(entry))
        from character_library import CharacterLibrary
        self.assertEqual(CharacterLibrary(lambda: self.media).list(), [entry])
        self.assertEqual(self.save_member(job).status_code, 200)
        self.assertEqual(self.members(), [entry], "idempotent keep preserves saved_at and name")
        response = self.client.delete(f"/api/characters/library/{job.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.members(), [])
        self.assertEqual(job.path.read_bytes(), original)
        self.assertTrue(Path(job.result).is_file())
        self.assertTrue(Path(job.meta["character_caption"]).is_file())
        self.assertEqual(self.client.get(f"/api/characters/jobs/{job.id}/capsule").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/characters/library/{job.id}").status_code, 200)

    def test_only_safe_completed_character_jobs_with_intact_artifacts_can_be_saved(self):
        for invalid in ("wrong", "A" * 32, "a" * 31, "a" * 33, "g" * 32):
            response = self.client.post(f"/api/characters/library/{invalid}", json={})
            self.assertEqual(response.status_code, 404, response.text)
        missing = self.client.post(f"/api/characters/library/{'a' * 32}", json={})
        self.assertEqual(missing.status_code, 404)
        job = core.Job(id="b" * 32, engine="other", status="done")
        job.save()
        self.assertEqual(self.save_member(job).status_code, 404)
        job.engine = "flux3-klein-character"
        for status in ("queued", "running", "error", "done"):
            job.status = status
            job.save()
            self.assertEqual(self.save_member(job).status_code, 409)
        job = self.completed()
        Path(job.result).write_bytes(b"broken png")
        response = self.save_member(job)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(str(self.root), response.text)
        job = self.completed()
        Path(job.meta["character_caption"]).unlink()
        self.assertEqual(self.save_member(job).status_code, 409)
        job = self.completed()
        job.meta["character_capsule"]["recipe_sha256"] = "0" * 64
        job.save()
        self.assertEqual(self.save_member(job).status_code, 409)
        job = self.completed()
        job.path.write_text("{not json")
        self.assertEqual(self.save_member(job).status_code, 409)
        job = self.completed()
        Path(job.result).unlink()
        self.assertEqual(self.save_member(job).status_code, 409)
        job = self.completed(image=b"not a PNG even with a matching capsule hash")
        self.assertEqual(self.save_member(job).status_code, 409)
        job = self.completed()
        job.meta = []
        job.save()
        self.assertEqual(self.save_member(job).status_code, 409)
        self.assertEqual(self.members(), [])

    def test_each_refusal_says_what_is_wrong(self):
        job = self.completed()
        Path(job.result).write_bytes(b"broken png")
        broken = self.save_member(job)
        self.assertEqual(broken.status_code, 409)
        job = self.completed()
        Path(job.meta["character_caption"]).unlink()
        missing = self.save_member(job)
        self.assertEqual(missing.status_code, 409)
        self.assertNotEqual(broken.json()["detail"], missing.json()["detail"])
        self.assertIn("image", broken.json()["detail"].lower())
        job = self.completed()
        Path(job.meta["character_caption"]).write_text("   ")
        empty = self.save_member(job)
        self.assertEqual(empty.status_code, 409)
        self.assertIn("caption", empty.json()["detail"].lower())

    def test_payload_validation_and_corrupt_index_are_path_free_and_never_overwritten(self):
        job = self.completed()
        for payload in ({"name": 7}, {"name": ""}, {"name": "x" * 101}, {"name": "bad\nname"}, {"extra": "x"}):
            response = self.client.post(f"/api/characters/library/{job.id}", json=payload)
            self.assertEqual(response.status_code, 422, response.text)
        self.index.parent.mkdir(parents=True, exist_ok=True)
        for bad in ("{", '[]', '{"version":1,"characters":[{"job_id":"bad"}]}'):
            self.index.write_text(bad)
            for method, path, kwargs in (
                ("get", "/api/characters/library", {}),
                ("post", f"/api/characters/library/{job.id}", {"json": {}}),
                ("delete", f"/api/characters/library/{job.id}", {}),
            ):
                response = getattr(self.client, method)(path, **kwargs)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertNotIn(str(self.root), response.text)
                self.assertEqual(self.index.read_text(), bad)

    def test_failed_atomic_replace_retains_previous_index_and_cleans_temporary(self):
        first, second = self.completed(), self.completed()
        self.assertEqual(self.save_member(first).status_code, 200)
        before = self.index.read_bytes()
        with patch("character_library.os.replace", side_effect=OSError(f"secret {self.root}")):
            response = self.save_member(second)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(str(self.root), response.text)
        self.assertEqual(self.index.read_bytes(), before)
        self.assertEqual(list(self.index.parent.glob("*.tmp")), [])
        self.assertEqual([entry["job_id"] for entry in self.members()], [first.id])

    def test_process_concurrent_updates_and_readers_do_not_lose_members(self):
        jobs = [self.completed() for _ in range(6)]
        ctx = multiprocessing.get_context("fork")
        with concurrent.futures.ProcessPoolExecutor(max_workers=3, mp_context=ctx) as pool:
            list(pool.map(_save_member, [str(self.root)] * len(jobs), [str(self.media)] * len(jobs), [j.id for j in jobs]))
        self.assertEqual({entry["job_id"] for entry in self.members()}, {j.id for j in jobs})
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda job: self.client.delete(f"/api/characters/library/{job.id}"), jobs[:3]))
        self.assertEqual({entry["job_id"] for entry in self.members()}, {j.id for j in jobs[3:]})


if __name__ == "__main__":
    unittest.main()
