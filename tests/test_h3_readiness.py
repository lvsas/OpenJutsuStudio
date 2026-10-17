"""H3 checks its own graph, never the LTX/FLUX inventory."""
import sys
import unittest
from pathlib import Path
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
        self.graph = build_h3_recast("s.mp4", "r.png", "Edit", source_frames=5)
        self.info = h3_info(self.graph)

    def test_h3_does_not_require_ltx_nodes(self):
        self.assertEqual(readiness._inventory(self.info, self.graph), ([], []))
        with patch.object(readiness, "comfy_base_url", return_value="http://127.0.0.1:8189"), \
             patch.object(readiness, "_json_get", side_effect=[
                 {"status": "healthy", "upstream": "http://127.0.0.1:8188"},
                 {"queue_running": [[1]], "queue_pending": []}, self.info]), \
             patch.object(readiness.shutil, "which", return_value="/bin/tool"):
            report = readiness.check_readiness(required_graph=self.graph)
        self.assertTrue(report["ready"], report)
        self.assertTrue(report["warnings"])

    def test_missing_upscaler_dynamic_combo_is_a_model_failure(self):
        self.info["MinimaxH3LatentUpscaler3D"]["input"]["required"]["model_name"][1]["options"] = []
        nodes, models = readiness._inventory(self.info, self.graph)
        self.assertEqual(nodes, [])
        self.assertEqual(models, [self.graph["169"]["inputs"]["model_name"]])

    def test_missing_h3_node_is_not_a_missing_ltx_dependency(self):
        del self.info["MiniMaxH3ReferenceToVideo"]
        nodes, _ = readiness._inventory(self.info, self.graph)
        self.assertEqual(nodes, ["MiniMaxH3ReferenceToVideo"])
