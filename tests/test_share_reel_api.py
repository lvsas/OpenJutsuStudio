"""CPU integration plus isolated concurrency/security tests for local reel artifacts."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import core
import share_reel_api as reels
from h3_recipe import digest_json
from media import ffprobe


class ReelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.media = self.root / "media"
        self.media.mkdir()
        self.work_patch = patch.object(core, "WORK", self.root)
        self.work_patch.start()
        self.service = reels.ReelService(lambda: self.media)
        app = FastAPI()
        app.include_router(reels.create_router(self.service))
        self.client = TestClient(app)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.work_patch.stop)
        self.addCleanup(self.service.close)
        self.job = self.make_job("take")

    def make_job(self, job_id, *, engine="ltx25-ripple"):
        source = self.media / f"{job_id}-source.mp4"
        result = self.media / f"{job_id}-result.mp4"
        source.write_bytes(b"source")
        result.write_bytes(b"result")
        job = core.Job(id=job_id, status="done", engine=engine, video=str(source), result=str(result))
        job.save()
        return job

    def post(self, job="take", layout="social", retry=False):
        return self.client.post(f"/api/jobs/{job}/reveal", params={"layout": layout, "retry": retry})

    def terminal(self, state):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            response = self.client.get(state["status_url"])
            self.assertEqual(response.status_code, 200, response.text)
            current = response.json()
            if current["status"] not in {"queued", "running"}:
                return current
            time.sleep(0.01)
        self.fail("Reel worker did not finish")

    @staticmethod
    def info(path):
        return {"width": 1080, "height": 1920, "frames": 24, "fps": 24.0, "duration": 1.0}

    @staticmethod
    def encode(source, result, output, **kwargs):
        output.write_bytes(b"0123456789")
        return str(output)

    def mocked(self, encoder=None):
        patches = [patch.object(reels, "ffprobe", side_effect=self.info),
                   patch.object(reels, "validate_reel_media", side_effect=lambda s, r: (self.info(s), self.info(r))),
                   patch.object(reels, "build_social_reel", side_effect=encoder or self.encode),
                   patch.object(reels, "build_comparison_reel", side_effect=encoder or self.encode)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return patches

    def test_real_social_render_async_reuse_and_media(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg unavailable")
        for path, color in ((self.job.video, "navy"), (self.job.result, "teal")):
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"color=c={color}:size=64x64:rate=24:duration=0.5",
                            "-c:v", "libx264", path], check=True, timeout=30)
        with patch("output_media.REEL_ASSET_DIR", self.root / "artwork"), \
                patch.object(reels, "build_social_reel", wraps=reels.build_social_reel) as encoder:
            response = self.post()
            self.assertEqual(response.status_code, 202, response.text)
            state = response.json()
            self.assertEqual(state["status"], "queued")
            self.assertIsNone(state["preview_url"])
            self.assertIsNone(state["download_url"])
            ready = self.terminal(state)
            self.assertEqual(ready["status"], "ready", ready)
            self.assertEqual(ready["renderer_version"], "social-v2")
            repeated = self.post()
            self.assertEqual(repeated.status_code, 200)
            self.assertEqual(repeated.json(), ready)
            self.assertEqual(self.post(retry=True).json(), ready)
            self.assertEqual(encoder.call_count, 1)
        inline = self.client.get(ready["preview_url"])
        self.assertEqual(inline.status_code, 200)
        self.assertEqual(inline.headers["content-type"], "video/mp4")
        self.assertTrue(inline.headers["content-disposition"].startswith("inline;"))
        download = self.client.get(ready["download_url"])
        self.assertTrue(download.headers["content-disposition"].startswith("attachment;"))
        part = self.client.get(ready["preview_url"], headers={"Range": "bytes=0-31"})
        self.assertEqual(part.status_code, 206)
        self.assertEqual(part.content, inline.content[:32])
        output = self.media / "reels" / "take" / ready["artifact_id"] / "reel.mp4"
        self.assertEqual(ffprobe(output)["frames"], 12)
        self.assertEqual(list(output.parent.glob(".*.part*")), [])
        persisted = json.loads((output.parent / "state.json").read_text())
        self.assertEqual(persisted["status"], "ready")
        self.assertNotIn(str(self.root), json.dumps(persisted))
        # A new service can serve previously committed artifacts without encoding again.
        restarted = reels.ReelService(lambda: self.media)
        try:
            self.assertEqual(restarted.status("take", ready["artifact_id"]), ready)
        finally:
            restarted.close()

    def test_singleflight_bounded_queue_truthful_states_and_no_partial_reads(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        calls = []

        def blocked(source, result, output, **kwargs):
            calls.append(str(output))
            output.write_bytes(b"partial")
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test release timeout")
            return self.encode(source, result, output)

        self.mocked(blocked)
        first = self.post().json()
        self.assertTrue(entered.wait(5))
        with ThreadPoolExecutor(max_workers=8) as requests:
            duplicates = list(requests.map(lambda _: self.post(), range(8)))
        for response in duplicates:
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["artifact_id"], first["artifact_id"])
            self.assertEqual(response.json()["status"], "running")
        self.assertEqual(len(calls), 1)
        media_url = first["status_url"] + "/media"
        self.assertEqual(self.client.get(media_url).status_code, 409)
        queued = []
        for index in range(3):
            self.make_job(f"queued-{index}")
            response = self.post(f"queued-{index}")
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["status"], "queued")
            queued.append(response.json())
        self.make_job("overflow")
        overflow = self.post("overflow")
        self.assertEqual(overflow.status_code, 429)
        self.assertEqual(overflow.headers["retry-after"], "2")
        self.assertFalse((self.media / "reels" / "overflow").exists())
        # Existing work is not rejected just because the queue has become full.
        self.assertEqual(self.post().status_code, 202)
        release.set()
        for state in [first, *queued]:
            self.assertEqual(self.terminal(state)["status"], "ready")
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.terminal(self.post("overflow").json())["status"], "ready")

    def test_real_h3_30fps_preparation_and_share_render(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg unavailable")
        from h3_media import prepare_source
        job, folder = self.h3_job(normalized=False)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=64x64:rate=30:duration=0.5", "-c:v", "libx264", job.video],
                       check=True, timeout=30)
        padded, count, padded_count = prepare_source(job.video, folder)
        normalized = folder / "normalized.mp4"
        shutil.copyfile(normalized, job.result)
        capsule = job.meta["h3_capsule"]
        capsule.pop("capsule_id")
        capsule["recipe"]["source_frames_24fps"] = count
        capsule["recipe_sha256"] = digest_json(capsule["recipe"])
        for role, path in (("source", job.video), ("result", job.result)):
            capsule["assets"][role] = {"sha256": reels._digest(Path(path)), "size_bytes": Path(path).stat().st_size}
        capsule["capsule_id"] = "sha256:" + digest_json(capsule)
        job.save()
        self.assertEqual(ffprobe(job.video)["fps"], 30)
        self.assertEqual(ffprobe(padded)["frames"], padded_count)
        self.assertGreater(padded_count, count)
        with patch("output_media.REEL_ASSET_DIR", self.root / "artwork"), \
                patch.object(reels, "build_social_reel", wraps=reels.build_social_reel) as encoder:
            response = self.post(job.id)
            self.assertEqual(response.status_code, 202)
            state = self.terminal(response.json())
            self.assertEqual(state["status"], "ready", state)
            self.assertEqual(encoder.call_args.args[0], normalized)
        output = self.media / "reels" / job.id / state["artifact_id"] / "reel.mp4"
        self.assertEqual(ffprobe(output)["frames"], count)
        self.assertEqual(ffprobe(output)["fps"], 24)

    def test_layouts_versions_engine_and_input_bytes_have_distinct_identity(self):
        self.mocked()
        states = [self.post(layout=layout).json() for layout in ("social", "wipe", "stacked")]
        states[0] = self.terminal(states[0])
        self.assertEqual(len({state["artifact_id"] for state in states}), 3)
        self.assertEqual(len({state["preview_url"] for state in states}), 3)
        self.assertTrue(states[1]["reveal_url"].endswith("/media"))
        self.assertEqual(self.client.get("/api/jobs/take/reveal?layout=stacked").status_code, 200)
        Path(self.job.result).write_bytes(b"changed result")
        changed = self.terminal(self.post().json())
        self.assertNotEqual(changed["artifact_id"], states[0]["artifact_id"])
        Path(self.job.video).write_bytes(b"changed source")
        changed_source = self.terminal(self.post().json())
        self.assertNotEqual(changed_source["artifact_id"], changed["artifact_id"])
        with patch.dict(reels.RENDERER_VERSIONS, {"social": "social-test-version"}):
            versioned = self.terminal(self.post().json())
        self.assertNotEqual(versioned["artifact_id"], changed_source["artifact_id"])
        self.job.engine = "test-engine"
        self.job.save()
        engine_changed = self.terminal(self.post().json())
        self.assertNotEqual(engine_changed["artifact_id"], changed_source["artifact_id"])
        self.assertEqual(self.client.get(states[0]["preview_url"]).status_code, 200)

    def test_timeout_encoder_and_validation_errors_are_path_free_and_retry_explicit(self):
        exceptions = [subprocess.TimeoutExpired(["ffmpeg", str(self.root)], 1),
                      subprocess.CalledProcessError(1, ["ffmpeg", str(self.root)], stderr=b"private path"),
                      ValueError(str(self.root)), OSError(str(self.root))]
        calls = []
        failure = [exceptions[0]]

        def fail(source, result, output, **kwargs):
            calls.append(output)
            output.write_bytes(b"partial bytes")
            raise failure[0]

        self.mocked(fail)
        for index, error in enumerate(exceptions):
            with self.subTest(error=type(error).__name__):
                failure[0] = error
                job = self.make_job(f"failure-{index}")
                failed = self.terminal(self.post(job.id).json())
                self.assertEqual(failed["status"], "error")
                self.assertNotIn(str(self.root), json.dumps(failed))
                self.assertNotIn("private path", json.dumps(failed))
                self.assertIsNone(failed["preview_url"])
                directory = self.media / "reels" / job.id / failed["artifact_id"]
                self.assertEqual(list(directory.glob(".*.part*")), [])
                self.assertFalse((directory / "reel.mp4").exists())
                self.assertEqual(self.client.get(failed["status_url"] + "/media").status_code, 409)
                before = len(calls)
                self.assertEqual(self.post(job.id).json(), failed)
                self.assertEqual(len(calls), before)
                with patch.object(reels, "build_social_reel", side_effect=self.encode):
                    retry = self.post(job.id, retry=True)
                    self.assertEqual(retry.status_code, 202)
                    ready = self.terminal(retry.json())
                    self.assertEqual(ready["artifact_id"], failed["artifact_id"])
                    self.assertEqual(ready["status"], "ready", ready)
                    self.assertNotIn("error", ready)

    def test_input_mutation_during_render_is_not_published(self):
        def mutate(source, result, output, **kwargs):
            self.encode(source, result, output)
            result.write_bytes(b"mutated during encoding")
        self.mocked(mutate)
        state = self.terminal(self.post().json())
        self.assertEqual(state["status"], "error")
        self.assertFalse((self.media / "reels" / "take" / state["artifact_id"] / "reel.mp4").exists())

    def test_submit_failure_is_persisted_without_leaking_queue_slots(self):
        self.mocked()
        with patch.object(self.service._executor, "submit", side_effect=RuntimeError(str(self.root))):
            failed = self.post()
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn(str(self.root), failed.text)
        self.assertEqual(self.service._active, set())
        persisted = self.post().json()
        self.assertEqual(persisted["status"], "error")
        self.assertEqual(self.terminal(self.post(retry=True).json())["status"], "ready")

    def test_corrupt_and_cross_bound_state_are_not_served(self):
        inputs = self.service.inputs("take", "social")
        artifact_id = reels._json_digest(inputs.identity)
        directory = self.service._directory(self.media, "take", artifact_id)
        directory.mkdir(parents=True)
        url = f"/api/jobs/take/reels/{artifact_id}"
        for state in ([], {"identity": []}, {"identity": {**inputs.identity, "job_id": "another"}, "status": "ready"}):
            with self.subTest(state=state):
                (directory / "state.json").write_text(json.dumps(state))
                self.assertEqual(self.client.get(url).status_code, 404)
        path = self.job.path
        data = json.loads(path.read_text())
        data["id"] = "another"
        path.write_text(json.dumps(data))
        self.assertEqual(self.post().status_code, 404)

    def test_invalid_output_is_not_published(self):
        self.mocked()
        with patch.object(reels, "ffprobe", return_value={**self.info(None), "frames": 23}):
            state = self.terminal(self.post().json())
        self.assertEqual(state["status"], "error")
        self.assertEqual(list((self.media / "reels").rglob("*.mp4")), [])

    def test_restart_interruption_is_error_until_explicit_retry(self):
        inputs = self.service.inputs("take", "social")
        artifact_id = reels._json_digest(inputs.identity)
        directory = self.service._directory(self.media, "take", artifact_id)
        for status in ("queued", "running"):
            with self.subTest(status=status):
                self.service._write(directory, {"identity": inputs.identity, "status": status})
                (directory / ".orphan.part.mp4").write_bytes(b"partial")
                result = self.client.get(f"/api/jobs/take/reels/{artifact_id}").json()
                self.assertEqual(result["status"], "error")
                self.assertIn("interrupted", result["error"])
                self.assertEqual(list(directory.glob(".*.part*")), [])
                self.assertEqual(self.post().json()["status"], "error")
        self.mocked()
        self.assertEqual(self.terminal(self.post(retry=True).json())["status"], "ready")

    def test_external_symlink_missing_and_cross_job_artifacts_are_refused(self):
        self.mocked()
        state = self.terminal(self.post().json())
        self.make_job("other")
        for suffix in ("", "/media"):
            self.assertEqual(self.client.get(f"/api/jobs/other/reels/{state['artifact_id']}{suffix}").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/take/reels/not-a-digest").status_code, 404)
        self.assertEqual(self.post(layout="unknown").status_code, 400)
        self.assertEqual(self.post("missing").status_code, 404)
        self.job.status = "running"
        self.job.save()
        self.assertEqual(self.post().status_code, 409)
        self.job.status = "done"
        with tempfile.TemporaryDirectory() as external:
            private = Path(external) / "private.mp4"
            private.write_bytes(b"outside workspace")
            for field in ("video", "result"):
                old = getattr(self.job, field)
                for use_symlink in (False, True):
                    with self.subTest(field=field, symlink=use_symlink):
                        candidate = private
                        if use_symlink:
                            candidate = self.media / f"escape-{field}.mp4"
                            candidate.symlink_to(private)
                        setattr(self.job, field, str(candidate))
                        self.job.save()
                        self.assertEqual(self.post().status_code, 404)
                setattr(self.job, field, old)
        # No basename rescue of a recorded missing path, despite a same-named local file.
        self.job.result = str(self.root / "missing" / Path(self.job.result).name)
        self.job.save()
        self.assertEqual(self.post().status_code, 404)

    def test_artifact_directory_and_ready_file_symlinks_are_not_served(self):
        self.mocked()
        ready = self.terminal(self.post().json())
        directory = self.media / "reels" / "take" / ready["artifact_id"]
        output = directory / "reel.mp4"
        output.unlink()
        output.symlink_to(self.job.result)
        self.assertEqual(self.client.get(ready["preview_url"]).status_code, 409)
        output.unlink()
        shutil.rmtree(directory)
        directory.symlink_to(self.media, target_is_directory=True)
        self.assertEqual(self.client.get(ready["status_url"]).status_code, 404)

    def h3_job(self, *, normalized=True):
        job = self.make_job("h3-take", engine="minimax-h3")
        folder = self.media / "h3-h3-take"
        folder.mkdir()
        if normalized:
            (folder / "normalized.mp4").write_bytes(b"normalized unpadded")
        (folder / "padded.mp4").write_bytes(b"not a comparison source")
        capsule = {"job_id": job.id, "engine": job.engine,
                   "recipe": {"source_frames_24fps": 24},
                   "assets": {role: {"sha256": reels._digest(Path(path)), "size_bytes": Path(path).stat().st_size}
                              for role, path in (("source", job.video), ("result", job.result))}}
        capsule["recipe_sha256"] = digest_json(capsule["recipe"])
        capsule["capsule_id"] = "sha256:" + digest_json(capsule)
        job.meta["h3_capsule"] = capsule
        job.save()
        return job, folder

    def test_h3_30fps_uses_own_unpadded_normalization_and_checks_provenance(self):
        job, folder = self.h3_job()
        used = []

        def encode(source, result, output, **kwargs):
            used.append(source)
            return self.encode(source, result, output)

        self.mocked(encode)
        with patch.object(reels, "ffprobe", side_effect=lambda path: {**self.info(path),
                          **({"fps": 30, "frames": 30} if Path(path) == Path(job.video) else {})}):
            state = self.terminal(self.post(job.id).json())
        self.assertEqual(state["status"], "ready", state)
        self.assertEqual(used, [folder / "normalized.mp4"])
        Path(job.video).write_bytes(b"tampered original")
        failed = self.terminal(self.post(job.id).json())
        self.assertEqual(failed["status"], "error")
        self.assertEqual(len(used), 1)

    def test_h3_legacy_aligned_original_is_usable_but_no_30fps_fallback(self):
        job, folder = self.h3_job(normalized=False)
        self.mocked()
        self.assertEqual(self.terminal(self.post(job.id).json())["status"], "ready")
        (folder / "normalized.mp4").write_bytes(b"new normalized source")
        with patch.object(reels, "validate_reel_media", return_value=(
                {**self.info(None), "fps": 30, "frames": 30}, self.info(None))):
            self.assertEqual(self.terminal(self.post(job.id).json())["status"], "error")

    def test_h3_refuses_other_jobs_normalized_file_and_wrong_duration(self):
        job, folder = self.h3_job()
        self.mocked()
        normalized = folder / "normalized.mp4"
        normalized.unlink()
        normalized.symlink_to(self.job.video)
        self.assertEqual(self.post(job.id).status_code, 404)
        normalized.unlink()
        normalized.write_bytes(b"wrong duration")
        with patch.object(reels, "ffprobe", return_value={**self.info(None), "duration": 2}):
            self.assertEqual(self.terminal(self.post(job.id).json())["status"], "error")


if __name__ == "__main__":
    unittest.main()
