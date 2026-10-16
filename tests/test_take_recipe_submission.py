from __future__ import annotations

import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app as app_module
import core
import job_api
from fastapi.testclient import TestClient


class InlineExecutor:
    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except BaseException as exc:
            future.set_exception(exc)
        return future


class TakeRecipeSubmissionTests(unittest.TestCase):
    def test_new_job_persists_effective_recipe_matching_runner_options(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = root / "result.mp4"
            result.write_bytes(b"finished")
            previous_work, previous_media = core.WORK, app_module.MEDIA_DIR
            core.WORK = root
            app_module.MEDIA_DIR = root / "media"
            observed = {}

            async def fake_save_video(upload, destination, _max_bytes):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(await upload.read())
                return {"width": 1280, "height": 704, "fps": 23.976, "frames": 121, "duration": 5.05}

            def fake_runner(job, video_path, opts):
                observed.update(opts=opts)
                job.status = "done"
                job.result = str(result)
                job.meta["shots"] = [{"start": 0, "end": 120}]
                job.save()

            try:
                with patch.object(app_module, "_EXECUTOR", InlineExecutor()), \
                     patch.object(app_module, "PIPELINE_RUNNER", fake_runner), \
                     patch.object(app_module, "check_readiness", return_value={"ready": True, "issues": []}), \
                     patch.object(job_api, "save_video", fake_save_video):
                    client = TestClient(app_module.app)
                    response = client.post(
                        "/api/jobs",
                        files={"video": ("source.mp4", b"local video", "video/mp4")},
                        data={"edit_prompt": "Change the jacket", "seed": "19", "ripple_strength": "1.15"},
                    )
                self.assertEqual(response.status_code, 202, response.text)
                job = core.Job.load(response.json()["job_id"])
                recipe = job.meta["take_recipe"]
                self.assertEqual(recipe["edit_seed"], observed["opts"]["edit"]["seed"])
                self.assertEqual(recipe["ripple_seed"], observed["opts"]["propagate"]["seed"])
                self.assertEqual(recipe["ripple_strength"], observed["opts"]["propagate"]["strength"])
                self.assertEqual(recipe["propagation_prompt"], observed["opts"]["ripple_prompt"])
                self.assertEqual(recipe["fps"], 23.976)
                self.assertEqual(recipe["model_files"]["ripple_lora"], "LTX25_Ripple_v11.safetensors")
            finally:
                core.WORK = previous_work
                app_module.MEDIA_DIR = previous_media


if __name__ == "__main__":
    unittest.main()
