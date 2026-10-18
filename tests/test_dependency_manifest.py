"""The dependency manifest and its checker, kept honest by the workflows themselves.

A manifest that drifts from the graphs is worse than none: it tells an installer the machine is
ready when it is not. These tests tie the manifest to what the workflows actually reference, and
exercise the checker on a synthetic inventory so its verdict is known before it is trusted.
"""
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dependencies.json"
FIELD_PREFIXES = ("unet_name", "vae_name", "clip_name", "lora_name", "ckpt_name")
MODEL_SUFFIXES = (".safetensors", ".gguf", ".pth", ".bin", ".ckpt")

spec = importlib.util.spec_from_file_location(
    "check_dependencies", ROOT / "scripts" / "check_dependencies.py")
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
sys.modules["check_dependencies"] = checker
spec.loader.exec_module(checker)


def graphs():
    return [json.loads(path.read_text()) for path in sorted((ROOT / "workflows").glob("*.json"))]


def workflow_node_classes():
    classes = set()
    for graph in graphs():
        for node in graph.values():
            if isinstance(node, dict) and "class_type" in node:
                classes.add(node["class_type"])
    source = (ROOT / "src" / "h3_graphs.py").read_text()
    classes.update(re.findall(r'class_type["\']?\s*[:=]\s*["\']([A-Za-z0-9_ ()]+)["\']', source))
    return classes


def workflow_model_files():
    names = set()
    for graph in graphs():
        for node in graph.values():
            if not isinstance(node, dict):
                continue
            for field, value in (node.get("inputs") or {}).items():
                if field.startswith(FIELD_PREFIXES) and isinstance(value, str):
                    names.add(value)
    source = (ROOT / "src" / "h3_graphs.py").read_text()
    names.update(re.findall(r'["\']([A-Za-z0-9_\-./ ]+\.(?:safetensors|gguf|pth|bin))["\']', source))
    return names


class ManifestShapeTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text())

    def test_the_manifest_declares_every_node_a_workflow_uses(self):
        declared = {node for pack in self.manifest["comfyui_packs"] for node in pack["nodes"]}
        declared |= set(self.manifest["core_nodes"]["from_comfy_extras"])
        declared |= set(self.manifest["core_nodes"]["from_core"])
        for node in sorted(workflow_node_classes()):
            with self.subTest(node=node):
                self.assertIn(node, declared, f"{node} is used but absent from dependencies.json")

    def test_the_manifest_declares_every_model_a_workflow_names(self):
        declared = {entry["file"] for entry in self.manifest["models"]}
        declared |= {entry["file"] for entry in self.manifest["loras"]}
        for name in sorted(workflow_model_files()):
            with self.subTest(model=name):
                self.assertIn(name, declared, f"{name} is named but absent from dependencies.json")

    def test_every_pack_says_which_workflow_needs_it(self):
        for pack in self.manifest["comfyui_packs"]:
            with self.subTest(pack=pack["name"]):
                self.assertTrue(pack["used_by"])
                self.assertTrue(pack["nodes"])

    def test_every_model_entry_has_a_known_comfyui_folder(self):
        allowed = set(checker.LOADER_FIELD)
        for entry in self.manifest["models"] + self.manifest["loras"]:
            with self.subTest(file=entry["file"]):
                self.assertIn(entry["folder"], allowed)
                self.assertIn("role", entry)

    def test_the_planned_character_generator_names_a_gated_repository(self):
        """Downloads need an authenticated client, so an installer has to be told."""
        planned = self.manifest["character_generator"]
        self.assertEqual(planned["status"], "planned")
        self.assertTrue(planned["gated_repository"])
        self.assertTrue(planned["diffusion_models"])
        self.assertTrue(planned["text_encoders"])


class CheckerTests(unittest.TestCase):
    """Drive the checker with a synthetic inventory: its verdict must be predictable."""

    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text())
        self.complete = {}
        for pack in self.manifest["comfyui_packs"]:
            for node in pack["nodes"]:
                self.complete[node] = {"python_module": f"custom_nodes.{pack['name']}"}
        for node in self.manifest["core_nodes"]["from_comfy_extras"] + \
                self.manifest["core_nodes"]["from_core"]:
            self.complete.setdefault(node, {"python_module": "nodes"})
        # every model present, under the loader field its folder maps to
        by_folder = {}
        for entry in self.manifest["models"] + self.manifest["loras"]:
            node, field = checker.LOADER_FIELD[entry["folder"]]
            by_folder.setdefault((node, field), set()).add(entry["file"])
        for (node, field), files in by_folder.items():
            self.complete.setdefault(node, {})["input"] = {
                "required": {field: [sorted(files), {}]}}

    def test_a_complete_machine_reports_nothing_missing(self):
        report = checker.check(self.complete, self.manifest)
        self.assertEqual(report["missing_nodes"], {})
        self.assertEqual(report["missing_models"], [])
        self.assertEqual(report["missing_core_nodes"], [])
        self.assertEqual(len(report["present_packs"]), len(self.manifest["comfyui_packs"]))

    def test_a_missing_node_is_named_even_when_its_siblings_are_present(self):
        # KJNodes carries four of the nodes we use, so removing one leaves siblings behind.
        broken = {k: v for k, v in self.complete.items() if k != "VAELoaderKJ"}
        report = checker.check(broken, self.manifest)
        pack = [name for name, detail in report["missing_nodes"].items()
                if "VAELoaderKJ" in detail["missing"]]
        self.assertTrue(pack, "the pack that owns VAELoaderKJ should be reported")
        # its siblings still resolve, which is what tells an installer the pack is installed
        self.assertTrue(report["missing_nodes"][pack[0]]["present"])

    def test_a_missing_model_is_named_with_the_loader_field_that_should_hold_it(self):
        broken = json.loads(json.dumps(self.complete))
        broken["UNETLoader"]["input"]["required"]["unet_name"] = [[], {}]
        report = checker.check(broken, self.manifest)
        named = {item["file"] for item in report["missing_models"]}
        self.assertIn("ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", named)
        self.assertTrue(all(item.get("loader") for item in report["missing_models"]))

    def test_an_old_comfyui_is_reported_as_such_not_as_a_missing_pack(self):
        old = {k: v for k, v in self.complete.items() if k != "MiniMaxH3ReferenceToVideo"}
        report = checker.check(old, self.manifest)
        self.assertIn("MiniMaxH3ReferenceToVideo", report["missing_core_nodes"])
        self.assertEqual(report["missing_nodes"], {},
                         "a core node must not be blamed on a custom pack")

    def test_the_planned_models_are_opt_in_and_marked(self):
        without = checker.check(self.complete, self.manifest)
        self.assertNotIn("flux3-image-klein-int8-convrot.safetensors",
                         {item["file"] for item in without["missing_models"]})
        with_planned = checker.check(self.complete, self.manifest, include_planned=True)
        planned = {item["file"] for item in with_planned["missing_models"] if item.get("planned")}
        self.assertIn("flux3-image-klein-int8-convrot.safetensors", planned)
        # and a planned miss must not be treated as a deployment failure
        self.assertTrue(all(item.get("planned") for item in with_planned["missing_models"]))

    def test_every_combo_shape_comfyui_has_used_is_read(self):
        """Reading only the old shapes reported a present file as missing, on a live instance."""
        file = "minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors"
        shapes = {
            "bare list of options": [[file, "other.safetensors"]],
            "list of options followed by a config dict": [[file, "other.safetensors"], {}],
            "COMBO with an options dict": ["COMBO", {"options": [file, "other.safetensors"]}],
            "bare dict with options": [{"options": [file, "other.safetensors"]}, {}],
        }
        for label, spec in shapes.items():
            with self.subTest(shape=label):
                inventory = {"MinimaxH3LatentUpscaler3D": {
                    "input": {"required": {"model_name": spec}}}}
                options = checker.loader_options(inventory, "MinimaxH3LatentUpscaler3D", "model_name")
                self.assertIn(file, options, f"the {label} shape was not read")


if __name__ == "__main__":
    unittest.main()
