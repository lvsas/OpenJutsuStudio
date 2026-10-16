"""Readiness is read-only, actionable, and separate from liveness."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app
import readiness
from graphs import build_frame_edit, build_ripple


def node_info():
    info = {}
    graph = [*build_frame_edit("x.png", "edit").values(),
             *build_ripple("x.mp4", "x.png").values()]
    for node in graph:
        inputs = info.setdefault(node["class_type"], {"input": {"required": {}}})["input"]["required"]
        for key, value in node["inputs"].items():
            if key in {"unet_name", "clip_name", "vae_name", "lora_name"}:
                inputs.setdefault(key, [[], {}])[0].append(value)
    return info


class ReadinessTests(unittest.TestCase):
    def responses(self, url):
        return {"status": "healthy", "upstream": "http://127.0.0.1:8188"} if url.endswith("health") else node_info()

    def test_ready_with_models_and_nodes(self):
        with patch.object(readiness, "_json_get", side_effect=self.responses), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["missing_nodes"], [])

    def test_busy_comfy_queue_is_not_ready_for_another_render(self):
        with patch.object(readiness, "_json_get", side_effect=[
            self.responses("health"), {"queue_running": [[1]], "queue_pending": []}
        ]), patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertFalse(report["ready"])
        self.assertIn("busy", report["issues"][0].lower())

    def test_missing_model_is_not_ready(self):
        info = node_info()
        info["UNETLoader"]["input"]["required"]["unet_name"][0] = []
        with patch.object(readiness, "_json_get", side_effect=[self.responses("health"), {}, info]), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertFalse(report["ready"])
        self.assertTrue(report["missing_models"])

    def test_downstream_unreachable_does_not_leak_error_details(self):
        with patch.object(readiness, "_json_get", side_effect=RuntimeError("secret-value")):
            report = readiness.check_readiness()
        self.assertFalse(report["ready"])
        self.assertNotIn("secret-value", str(report))
        self.assertTrue(report["issues"])

    def test_unready_api_does_not_store_upload(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, "MEDIA_DIR", Path(tmp)), \
             patch.object(app, "check_readiness", return_value={"ready": False, "issues": ["Start Comfy API Proxy"]}):
            client = TestClient(app.app)
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/api/readiness").status_code, 503)
            r = client.post("/api/jobs", files={"video": ("a.mp4", b"video", "video/mp4")},
                            data={"edit_prompt": "replace object"})
            self.assertEqual(r.status_code, 503, r.text)
            self.assertEqual(list(Path(tmp).iterdir()), [])
