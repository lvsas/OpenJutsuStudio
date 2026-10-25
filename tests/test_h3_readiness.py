"""H3 checks its own graph, never the LTX/FLUX inventory."""
import sys
import unittest
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from h3_graphs import build_h3_recast
import readiness


def h3_info(graph):
    info = {}
    for n in graph.values():
        specs = info.setdefault(n["class_type"], {"input": {"required": {}}})["input"]["required"]
        for k, v in n["inputs"].items():
            if k in {"unet_name", "clip_name", "vae_name", "lora_name"}:
                specs.setdefault(k, [[], {}])[0].append(v)
            if k == "model_name":
                specs[k] = ["COMBO", {"options": [v]}]
    return info


class H3ReadinessTests(unittest.TestCase):
    def setUp(self):
        with readiness._OBJECT_INFO_LOCK:
            readiness._OBJECT_INFO_CACHE.clear()
        self.graph = build_h3_recast("s.mp4", "r.png", "Edit", source_frames=5)
        self.info = h3_info(self.graph)

    def responses(self, url, headers=None, timeout=None):
        path = urlsplit(url).path
        if path == '/api/v2/health':
            return {"status": "healthy", "upstream": "http://127.0.0.1:8188"}
        if path == '/queue':
            return {"queue_running": [[1]], "queue_pending": []}
        if path.startswith('/object_info/'):
            name = unquote(path.removeprefix('/object_info/'))
            return {name: self.info[name]} if name in self.info else {}
        raise AssertionError(url)

    def test_h3_readiness_uses_only_its_classes_when_full_registry_times_out(self):
        seen = []

        def get(url, headers=None, timeout=None):
            seen.append(url)
            if url.endswith('/object_info'):
                raise TimeoutError('unrelated full registry is too large')
            return self.responses(url, headers, timeout)

        with patch.object(readiness, "comfy_base_url", return_value="http://127.0.0.1:8189"), \
             patch.object(readiness, "_json_get", side_effect=get), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness(required_graph=self.graph)
        self.assertTrue(report['ready'], report)
        expected = ['http://127.0.0.1:8188/object_info/' + quote(name, safe='')
                    for name in sorted(self.info)]
        self.assertEqual(seen[2:], expected)

    def test_h3_does_not_require_ltx_nodes(self):
        self.assertEqual(readiness._inventory(self.info, self.graph), ([], []))
        with patch.object(readiness, "comfy_base_url", return_value="http://127.0.0.1:8189"), \
             patch.object(readiness, "_json_get", side_effect=self.responses), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness(required_graph=self.graph)
        self.assertTrue(report["ready"], report)
        self.assertTrue(report["warnings"])

    def test_missing_upscaler_dynamic_combo_is_a_model_failure(self):
        self.info["MinimaxH3LatentUpscaler3D"]["input"]["required"]["model_name"][1]["options"] = []
        nodes, models = readiness._inventory(self.info, self.graph)
        self.assertEqual(nodes, [])
        self.assertEqual(models, [self.graph["169"]["inputs"]["model_name"]])
        with patch.object(readiness, "comfy_base_url", return_value="http://127.0.0.1:8189"), \
             patch.object(readiness, "_json_get", side_effect=self.responses), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness(self.graph)
        self.assertFalse(report['ready'], report)
        self.assertEqual(report['missing_nodes'], [])
        self.assertEqual(report['missing_models'], models)

    def test_missing_h3_node_is_not_a_missing_ltx_dependency(self):
        del self.info["MiniMaxH3ReferenceToVideo"]
        nodes, _ = readiness._inventory(self.info, self.graph)
        self.assertEqual(nodes, ["MiniMaxH3ReferenceToVideo"])
        with patch.object(readiness, "comfy_base_url", return_value="http://127.0.0.1:8189"), \
             patch.object(readiness, "_json_get", side_effect=self.responses), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness(self.graph)
            missing_nodes, _ = readiness.missing_dependencies(self.graph)
        self.assertFalse(report['ready'], report)
        self.assertEqual(report['missing_nodes'], nodes)
        self.assertEqual(missing_nodes, nodes)

    def test_timeout_is_actionable_and_not_reported_as_missing_models(self):
        seen = []
        def get(url, headers=None, timeout=None):
            seen.append(url)
            if '/object_info/' in url:
                raise TimeoutError("private target detail")
            return self.responses(url, headers, timeout)
        with patch.object(readiness, "comfy_base_url", return_value="http://127.0.0.1:8189"), \
             patch.object(readiness, "_json_get", side_effect=get), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness(required_graph=self.graph)
        self.assertFalse(report["ready"])
        self.assertIn("timed out", " ".join(report["issues"]).lower())
        self.assertEqual(report["missing_nodes"], [])
        self.assertEqual(report["missing_models"], [])
        self.assertNotIn("private target detail", str(report))
        self.assertEqual(len(seen), 3)
        self.assertIn('/object_info/', seen[-1])

    def test_readiness_and_target_preflight_share_class_cache(self):
        with patch.object(readiness, "comfy_base_url", return_value="http://127.0.0.1:8189"), \
             patch.object(readiness, "_json_get", side_effect=self.responses) as get, \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness(self.graph)
            self.assertEqual(readiness.missing_dependencies(self.graph), ([], []))
        self.assertTrue(report['ready'], report)
        urls = [call.args[0] for call in get.call_args_list]
        self.assertEqual(urls.count('http://127.0.0.1:8189/api/v2/health'), 2)
        classes = [url for url in urls if '/object_info/' in url]
        self.assertEqual(classes, ['http://127.0.0.1:8188/object_info/' + quote(name, safe='')
                                   for name in sorted(self.info)])

    def test_unreadable_class_inventory_is_not_ready_or_optimistic_preflight(self):
        def get(url, headers=None, timeout=None):
            if '/object_info/' in url:
                return []
            return self.responses(url, headers, timeout)
        with patch.object(readiness, "comfy_base_url", return_value="http://127.0.0.1:8189"), \
             patch.object(readiness, "_json_get", side_effect=get), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness(self.graph)
            with self.assertRaisesRegex(ValueError, 'inventory could not be read'):
                readiness.missing_dependencies(self.graph)
        self.assertFalse(report['ready'], report)
