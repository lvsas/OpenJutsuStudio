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
        self.assertIn("LTX 2.5 + Ripple", page.text)

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
                    "ripple_strength": "1.2",
                },
            )
        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()["job_id"]
        job = app_module.core.Job.load(job_id)
        self.assertEqual(job.status, "done")
        self.assertTrue(observed["video_path"].is_file())
        self.assertEqual(observed["opts"]["propagate"]["frames"], 121)
        self.assertEqual(observed["opts"]["propagate"]["width"], 768)
        self.assertEqual(observed["opts"]["propagate"]["height"], 416)
        self.assertEqual(observed["opts"]["propagate"]["strength"], 1.2)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["status"], "done")

    def test_rejects_unsupported_extension(self):
        response = self.client.post(
            "/api/jobs",
            files={"video": ("payload.txt", b"x", "text/plain")},
            data={"edit_prompt": "Change the object"},
        )
        self.assertEqual(response.status_code, 415)

    def test_target_size_preserves_landscape_and_portrait(self):
        self.assertEqual(app_module._target_size(1280, 704), (768, 416))
        self.assertEqual(app_module._target_size(704, 1280), (416, 768))


if __name__ == "__main__":
    unittest.main()
