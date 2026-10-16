from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app as app_module
import core
from fastapi.testclient import TestClient


class InlineExecutor:
    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except BaseException as exc:
            future.set_exception(exc)
        return future


class TakeCapsuleApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_work = core.WORK
        core.WORK = self.root
        self.source = self.root / "source.mp4"
        self.reference = self.root / "ref.png"
        self.result = self.root / "result.mp4"
        self.source.write_bytes(b"source-bytes")
        self.reference.write_bytes(b"reference-bytes")
        self.result.write_bytes(b"result-bytes")
        self.recipe = {
            "schema_version": 1,
            "edit_brief": "Change the jacket",
            "target_description": "the rider",
            "effective_edit_prompt": "compiled edit prompt",
            "propagation_prompt": "compiled motion prompt",
            "edit_seed": 19,
            "edit_steps": 4,
            "edit_cfg": 1.0,
            "edit_megapixels": 1.0,
            "ripple_seed": 19,
            "ripple_steps": 16,
            "ripple_strength": 1.2,
            "ripple_cfg": 1.0,
            "guide_strength": 1.0,
            "frames": 9,
            "fps": 24.0,
            "width": 704,
            "height": 384,
            "preserve_audio": True,
            "upscale": False,
            "model_files": {"ripple_lora": "local-model.safetensors"},
        }
        self.parent = core.Job(
            id="capsule-parent",
            status="done",
            engine="ltx25-ripple",
            prompt="compiled edit prompt",
            video=str(self.source),
            result=str(self.result),
            created=123.0,
            meta={
                "take_recipe": self.recipe,
                "references": [{"target": "rider", "image": str(self.reference)}],
                "shots": [{"start": 0, "end": 8, "source_frames": 9}],
            },
        )
        self.parent.save()
        self.client = TestClient(app_module.app)

    def tearDown(self):
        core.WORK = self.old_work
        self.temp.cleanup()

    def test_capsule_is_path_free_and_hashes_all_local_assets(self):
        response = self.client.get(f"/api/jobs/{self.parent.id}/capsule")
        self.assertEqual(response.status_code, 200, response.text)
        manifest = response.json()
        self.assertEqual(manifest["format"], "opengenjutsu-take-capsule")
        self.assertTrue(manifest["replay"]["available_on_this_machine"])
        self.assertEqual(manifest["shot_boundaries"][0]["end"], 8)
        self.assertEqual(manifest["assets"]["source"]["sha256"], hashlib.sha256(b"source-bytes").hexdigest())
        self.assertEqual(manifest["assets"]["references"][0]["sha256"], hashlib.sha256(b"reference-bytes").hexdigest())
        self.assertEqual(manifest["assets"]["result"]["sha256"], hashlib.sha256(b"result-bytes").hexdigest())
        self.assertNotIn(str(self.root), json.dumps(manifest))
        self.assertEqual(manifest["replay"]["model_weights_hashed"], False)

    def test_source_is_served_inline_for_replay_comparison(self):
        response = self.client.get(f"/api/jobs/{self.parent.id}/source")
        self.assertEqual(response.status_code, 200)
        self.assertIn("inline", response.headers["content-disposition"])
        self.assertEqual(response.content, b"source-bytes")

    def test_capsule_download_is_json_attachment(self):
        response = self.client.get(f"/api/jobs/{self.parent.id}/capsule?download=true")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment; filename=", response.headers["content-disposition"])
        self.assertEqual(json.loads(response.text)["job_id"], self.parent.id)

    def test_replay_creates_child_with_recipe_and_recorded_shots(self):
        captured = {}

        def fake_runner(job, video_path, opts):
            captured.update(job=job, video_path=video_path, opts=opts)

        with patch.object(app_module, "PIPELINE_RUNNER", fake_runner), \
             patch.object(app_module, "_EXECUTOR", InlineExecutor()), \
             patch.object(app_module, "check_readiness", return_value={"ready": True, "issues": []}):
            response = self.client.post(f"/api/jobs/{self.parent.id}/replay")

        self.assertEqual(response.status_code, 202, response.text)
        payload = response.json()
        self.assertEqual(payload["parent_job_id"], self.parent.id)
        child = core.Job.load(payload["job_id"])
        self.assertEqual(child.meta["parent_job_id"], self.parent.id)
        self.assertEqual(child.meta["take_recipe"], self.recipe)
        self.assertEqual(captured["video_path"], self.source)
        self.assertEqual(captured["opts"]["shots"], [{"start": 0, "end": 8}])
        self.assertEqual(captured["opts"]["edit"]["seed"], self.recipe["edit_seed"])
        self.assertEqual(captured["opts"]["propagate"]["strength"], self.recipe["ripple_strength"])

    def test_replay_rejects_missing_reference_without_dispatch(self):
        self.reference.unlink()
        with patch.object(app_module, "check_readiness", return_value={"ready": True, "issues": []}), \
             patch.object(app_module, "PIPELINE_RUNNER") as runner:
            response = self.client.post(f"/api/jobs/{self.parent.id}/replay")
        self.assertEqual(response.status_code, 409)
        runner.assert_not_called()

    def test_legacy_job_without_recipe_cannot_be_replayed(self):
        old = core.Job(
            id="legacy-take", status="done", video=str(self.source), result=str(self.result),
            meta={"shots": [{"start": 0, "end": 8}]},
        )
        old.save()
        response = self.client.post(f"/api/jobs/{old.id}/replay")
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
