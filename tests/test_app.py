from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app as app_module


class _ImmediateExecutor:
    """Run the worker inline so API tests never touch ComfyUI or race a thread."""
    def submit(self, fn, *args, **kwargs):
        from concurrent.futures import Future
        future = Future()
        future.set_running_or_notify_cancel()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.patches = [
            patch.object(app_module, "check_readiness", return_value={"ready": True, "issues": []}),
            patch.object(app_module.core, "WORK", root),
            patch.object(app_module, "MEDIA_DIR", root / "media"),
            patch.object(app_module, "_EXECUTOR", _ImmediateExecutor()),
            patch.object(app_module.core, "ffprobe", lambda _path: {
                "width": 1280, "height": 704, "fps": 24.0,
                "frames": 121, "duration": 5.04,
            }),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        app_module.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.client = TestClient(app_module.app)

    def test_health_and_home(self):
        self.assertEqual(
            self.client.get("/health").json(),
            {"status": "ok", "engine": "ltx25-ripple"},
        )
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("OpenGenjutsu", page.text)
        self.assertIn("LTX Creative Studio", page.text)
        self.assertIn('<html lang="en"', page.text)
        self.assertIn("/static/design-system.css", page.text)
        self.assertIn('data-engine="ltx"', page.text)
        self.assertIn('id="recipe-panel"', page.text)
        self.assertIn('id="studio-stage"', page.text)
        self.assertIn('data-drop-kind="video"', page.text)
        self.assertIn('data-drop-kind="image"', page.text)
        self.assertIn('id="compare-stage"', page.text)
        self.assertIn('id="show-compare"', page.text)
        self.assertIn('id="progress-label"', page.text)
        self.assertIn('role="progressbar"', page.text)
        self.assertNotIn('name="target_description"', page.text)
        self.assertIn("What should change?", page.text)
        self.assertNotIn("Target to edit", page.text)
        self.assertIn("Name the person and change in one sentence.", page.text)
        self.assertIn("Character reference", page.text)
        self.assertIn('name="reference_images"', page.text)
        self.assertIn('name="reference_targets"', page.text)
        self.assertIn('id="add-second-reference"', page.text)
        self.assertIn('id="second-reference" class="secondary-reference" hidden', page.text)
        self.assertIn('id="reference-mapping" class="reference-mapping" hidden', page.text)
        self.assertIn("Add a second character", page.text)
        self.assertIn("experimental", page.text)
        self.assertIn("Character recast is the first active mode", page.text)
        self.assertNotIn("character or object", page.text)
        self.assertIn('title="Additional studio modes are in development">More <span>Soon</span></button>', page.text)
        self.assertNotIn("H" + "3", page.text)
        self.assertNotIn("Mini" + "Max", page.text)
        self.assertIn("Studio HD", page.text)
        self.assertIn("Download MP4", page.text)
        self.assertIn("Copy caption", page.text)
        self.assertIn("Public result links activate only when the studio is hosted.", page.text)
        self.assertNotIn("twitter.com/intent", page.text)
        self.assertNotIn('name="propagation_prompt"', page.text)

    def test_video_upload_queues_pipeline_and_persists_job(self):
        observed = {}

        def fake_runner(job, video_path, opts):
            observed.update(job=job, video_path=video_path, opts=opts)
            job.status = "done"
            job.step = "done"
            job.progress = 1.0
            job.result = "test.mp4"
            job.save()

        with patch.object(app_module, "PIPELINE_RUNNER", fake_runner):
            response = self.client.post(
                "/api/jobs",
                files={"video": ("sample.mp4", b"test clip", "video/mp4")},
                data={
                    "edit_prompt": "Replace the red bag with a blue one",
                    "target_description": "the bag held by the person on the left",
                    "ripple_strength": "1.2",
                },
            )
        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()["job_id"]
        job = app_module.core.Job.load(job_id)
        self.assertEqual(job.status, "done")
        self.assertTrue(observed["video_path"].is_file())
        self.assertEqual(observed["opts"]["propagate"]["frames"], 121)
        self.assertEqual(observed["opts"]["propagate"]["width"], 1280)
        self.assertEqual(observed["opts"]["propagate"]["height"], 704)
        self.assertEqual(observed["opts"]["propagate"]["steps"], 16)
        self.assertEqual(observed["opts"]["propagate"]["strength"], 1.2)
        self.assertEqual(job.meta["target_description"], "the bag held by the person on the left")
        self.assertEqual(
            job.prompt,
            "Target to change: the bag held by the person on the left. Requested edit: Replace the red bag with a blue one",
        )
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["status"], "done")

    def test_video_and_character_reference_are_queued(self):
        observed = {}

        def fake_runner(job, video_path, opts):
            observed.update(job=job, video_path=video_path, opts=opts)
            job.status = "done"
            job.step = "done"
            job.progress = 1.0
            job.result = "test.mp4"
            job.save()

        with patch.object(app_module, "PIPELINE_RUNNER", fake_runner):
            response = self.client.post(
                "/api/jobs",
                files={
                    "video": ("sample.mp4", b"test clip", "video/mp4"),
                    "reference_image": ("character.png", b"fake image", "image/png"),
                },
                data={"edit_prompt": "Replace the performer with this character"},
            )
        self.assertEqual(response.status_code, 202, response.text)
        reference_path = observed["opts"]["reference_image"]
        self.assertTrue(reference_path.is_file())
        self.assertEqual(reference_path.suffix, ".png")
        self.assertEqual(observed["job"].meta["reference_image"], str(reference_path))

    def test_two_character_references_are_persisted_in_order(self):
        observed = {}

        def fake_runner(job, video_path, opts):
            observed.update(job=job, opts=opts)
            job.status = "done"
            job.result = "test.mp4"
            job.save()

        with patch.object(app_module, "PIPELINE_RUNNER", fake_runner):
            response = self.client.post(
                "/api/jobs",
                files=[
                    ("video", ("sample.mp4", b"test clip", "video/mp4")),
                    ("reference_images", ("left.png", b"left", "image/png")),
                    ("reference_images", ("right.png", b"right", "image/png")),
                ],
                data={
                    "edit_prompt": "Recast both performers",
                    "reference_targets": ["the performer on the left", "the performer on the right"],
                },
            )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(len(observed["opts"]["reference_images"]), 2)
        self.assertEqual([item["target"] for item in observed["job"].meta["references"]], [
            "the performer on the left", "the performer on the right",
        ])
        self.assertIn("Reference 1 applies to: the performer on the left.", observed["job"].prompt)
        self.assertIn("Reference 2 applies to: the performer on the right.", observed["job"].prompt)

    def test_rejects_unsupported_extension(self):
        response = self.client.post(
            "/api/jobs",
            files={"video": ("payload.txt", b"x", "text/plain")},
            data={"edit_prompt": "Change the object"},
        )
        self.assertEqual(response.status_code, 415)

    def test_target_size_uses_consistent_hd_megapixels_for_every_aspect(self):
        self.assertEqual(app_module._target_size(1920, 1080), (1280, 704))
        self.assertEqual(app_module._target_size(1080, 1920), (704, 1280))
        self.assertEqual(app_module._target_size(1440, 1080), (1088, 832))
        self.assertEqual(app_module._target_size(1080, 1080), (960, 960))

    def test_upload_character_sheet(self):
        response = self.client.post(
            "/api/upload-character",
            files={"file": ("ref.png", b"fake-image-data", "image/png")}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("asset_id", data)

    def test_compare_endpoint(self):
        """/api/compare should return source and edited frame paths."""
        # Create a job first so it exists
        import core as _core
        job = _core.Job(id="test-compare-001", prompt="test")
        job.save()

        response = self.client.get(
            "/api/compare",
            params={"job_id": "test-compare-001", "segment": 0}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("source_frame", data)
        self.assertIn("edited_frame", data)


if __name__ == "__main__":
    unittest.main()
