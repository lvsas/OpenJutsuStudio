"""Readiness is read-only, actionable, and separate from liveness."""
import os
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
    def setUp(self):
        with readiness._OBJECT_INFO_LOCK:
            readiness._OBJECT_INFO_CACHE.clear()

    def responses(self, url, headers=None, timeout=None):
        return {"status": "healthy", "upstream": "http://127.0.0.1:8188"} if url.endswith("health") else node_info()

    def test_ready_with_models_and_nodes(self):
        with patch.object(readiness, "_json_get", side_effect=self.responses), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["missing_nodes"], [])

    def test_json_get_honors_bounded_timeout_argument(self):
        with patch.object(readiness, "urlopen") as open_request, \
             patch.object(readiness.json, "load", return_value={"ok": True}):
            result = readiness._json_get("https://comfy.example/object_info", timeout=15)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(open_request.call_args.kwargs["timeout"], 15)

    def test_capability_inventory_uses_extended_timeout(self):
        with patch.object(readiness, "_json_get", return_value={}) as get:
            self.assertEqual(readiness._object_info("https://comfy.example/object_info"), {})
        self.assertEqual(get.call_args.kwargs["timeout"], readiness.CAPABILITY_TIMEOUT_SECONDS)
        self.assertGreater(readiness.CAPABILITY_TIMEOUT_SECONDS, readiness.READINESS_HTTP_TIMEOUT_SECONDS)

    def test_self_hosted_caches_object_info_but_checks_queue_each_time(self):
        readiness._OBJECT_INFO_CACHE.clear()
        counts = {"health": 0, "queue": 0, "object_info": 0}
        def get(url, headers=None, timeout=None):
            if url.endswith('/api/v2/health'):
                counts['health'] += 1
                return {"status": "healthy", "upstream": "http://127.0.0.1:8188"}
            if url.endswith('/queue'):
                counts['queue'] += 1
                return {"queue_running": [[1]], "queue_pending": []} if counts['queue'] == 1 else {"queue_running": [], "queue_pending": []}
            if url.endswith('/object_info'):
                counts['object_info'] += 1
                return node_info()
            raise AssertionError(url)
        try:
            with patch.object(readiness, "comfy_base_url", return_value="http://127.0.0.1:8189"), \
                 patch.object(readiness, "_json_get", side_effect=get), \
                 patch.object(readiness.shutil, "which", return_value="/bin/tool"):
                first = readiness.check_readiness()
                second = readiness.check_readiness()
            self.assertTrue(first['ready'], first)
            self.assertTrue(second['ready'], second)
            self.assertTrue(first['warnings'])
            self.assertFalse(second['warnings'])
            self.assertEqual(counts, {"health": 2, "queue": 2, "object_info": 1})
        finally:
            readiness._OBJECT_INFO_CACHE.clear()

    def test_busy_queue_warns_but_allows_sequential_submission(self):
        with patch.object(readiness, "_json_get", side_effect=[
            self.responses("health"), {"queue_running": [[1]], "queue_pending": []}, node_info()
        ]), patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["issues"], [])
        self.assertIn("queue", " ".join(report["warnings"]).lower())

    def test_pending_queue_does_not_skip_missing_model_checks(self):
        info = node_info()
        info["UNETLoader"]["input"]["required"]["unet_name"][0] = []
        with patch.object(readiness, "_json_get", side_effect=[
            self.responses("health"), {"queue_running": [], "queue_pending": [[1]]}, info
        ]), patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertFalse(report["ready"])
        self.assertTrue(report["missing_models"])
        self.assertTrue(report["warnings"])

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

    def test_cloud_readiness_uses_api_key_and_checks_node_inventory(self):
        base = "https://cloud.comfy.org"
        seen = []

        def get(url, headers=None, timeout=None):
            seen.append((url, headers or {}))
            if url.endswith("/api/object_info"):
                return node_info()
            raise AssertionError(f"Unexpected Cloud probe: {url}")

        with patch.object(readiness, "comfy_base_url", return_value=base), \
             patch.dict(os.environ, {"COMFY_API_KEY": "test-cloud-key"}, clear=True), \
             patch.object(readiness, "_json_get", side_effect=get), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["mode"], "comfy-cloud")
        self.assertEqual(report["missing_nodes"], [])
        self.assertIn((base + "/api/object_info", {"X-API-Key": "test-cloud-key"}), seen)
        self.assertNotIn("test-cloud-key", str(report))

    def test_cloud_without_api_key_is_actionable_without_request(self):
        with patch.object(readiness, "comfy_base_url", return_value="https://cloud.comfy.org"), \
             patch.dict(os.environ, {}, clear=True), \
             patch.object(readiness, "_json_get") as request, \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertFalse(report["ready"])
        self.assertIn("COMFY_API_KEY", " ".join(report["issues"]))
        request.assert_not_called()

    def test_remote_proxy_health_does_not_probe_private_upstream(self):
        base = "https://studio.example.invalid"
        seen = []

        def get(url, headers=None):
            seen.append(url)
            if url == base + "/api/v2/health":
                return {"status": "healthy", "upstream": "http://127.0.0.1:8188"}
            if url == base + "/api/v2/jobs?limit=1":
                return {"jobs": []}
            raise AssertionError(f"Unexpected remote probe: {url}")

        with patch.object(readiness, "comfy_base_url", return_value=base), \
             patch.dict(os.environ, {}, clear=True), \
             patch.object(readiness, "_json_get", side_effect=get), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertTrue(report["ready"], report)
        self.assertEqual(report["mode"], "remote-self-hosted")
        self.assertTrue(report["warnings"])
        self.assertEqual(seen, [base + "/api/v2/health", base + "/api/v2/jobs?limit=1"])
        self.assertNotIn("127.0.0.1:8188", str(report))

    def test_deployment_uses_authenticated_v2_not_cloud_v1_inventory(self):
        base = "https://test.run.comfy.app"
        with patch.object(readiness, "comfy_base_url", return_value=base), \
             patch.dict(os.environ, {"COMFY_API_KEY": "test-key"}, clear=True), \
             patch.object(readiness, "_json_get", return_value={"jobs": []}) as get, \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertTrue(report["ready"], report)
        get.assert_called_once_with(base + "/api/v2/jobs?limit=1", {"Authorization": "Bearer test-key"})
        self.assertEqual(report["mode"], "comfy-api-deployment")
        self.assertTrue(report["warnings"])
        self.assertNotIn("test-key", str(report))

    def test_remote_health_success_cannot_hide_auth_failure(self):
        with patch.object(readiness, "comfy_base_url", return_value="https://studio.example.invalid"), \
             patch.object(readiness, "_json_get", side_effect=[
                 self.responses("health"), RuntimeError("401 secret-key")]), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertFalse(report["ready"])
        self.assertNotIn("secret-key", str(report))

    def test_deployment_without_credentials_never_probes(self):
        with patch.object(readiness, "comfy_base_url", return_value="https://test.run.comfy.app"), \
             patch.dict(os.environ, {}, clear=True), \
             patch.object(readiness, "_json_get") as get, \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertFalse(report["ready"])
        get.assert_not_called()

    def test_invalid_v2_listing_is_not_ready(self):
        with patch.object(readiness, "comfy_base_url", return_value="https://test.run.comfy.app"), \
             patch.dict(os.environ, {"COMFY_API_KEY": "test-key"}, clear=True), \
             patch.object(readiness, "_json_get", return_value={"status": "healthy"}), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness()
        self.assertFalse(report["ready"])

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
