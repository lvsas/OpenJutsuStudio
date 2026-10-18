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

    def test_the_character_generator_names_a_gated_repository_and_its_roles(self):
        """Downloads need an authenticated client, so an installer has to be told."""
        planned = self.manifest["character_generator"]
        self.assertIn(planned["status"], {"planned", "partially_installed", "installed"})
        self.assertTrue(planned["gated_repository"])
        roles = {role["role"] for role in planned["roles"]}
        self.assertIn("diffusion model", roles)
        self.assertTrue(any("encoder" in name for name in roles),
                        "a conditioning encoder must be declared")
        for role in planned["roles"]:
            with self.subTest(role=role["role"]):
                self.assertTrue(role["alternatives"], "a role must say what could satisfy it")
                self.assertTrue(role["note"], "and why it is needed")

    def test_an_installed_file_is_one_of_its_role_alternatives(self):
        """Not a record of today's machine: the file named as installed must be a valid answer."""
        for role in self.manifest["character_generator"]["roles"]:
            with self.subTest(role=role["role"]):
                if role["installed"] is not None:
                    self.assertIn(role["installed"], role["alternatives"])

    def test_the_upsampler_is_not_declared_as_the_conditioning_encoder(self):
        """The name says upsampler, so it was wired to the sampler and failed on tensor shapes."""
        named = [r for r in self.manifest["character_generator"]["roles"]
                 if "upsampler" in r["role"]]
        self.assertTrue(named, "the upsampler is installed and worth recording")
        for role in named:
            with self.subTest(role=role["role"]):
                self.assertFalse(role["required"],
                                 "an upsampler writes text; a graph can sample without it")
                self.assertIn("NOT the conditioning encoder", role["note"],
                              "the note must say what it is not, or the next reader repeats it")

    def test_the_verified_combination_names_every_part_it_exercised(self):
        verified = self.manifest["character_generator"]["verified_combination"]
        for part in ("diffusion", "encoder", "encoder_type", "vae", "evidence"):
            with self.subTest(part=part):
                self.assertTrue(verified[part])


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
        # the character generator's installed files, so its roles can be evaluated too
        for role in self.manifest["character_generator"]["roles"]:
            if role.get("installed"):
                by_folder.setdefault(("UNETLoader", "unet_name"), set()).add(role["installed"])
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

    def test_a_role_is_satisfied_only_by_a_file_the_inventory_reports(self):
        """The verdict must follow the inventory, not a hard-coded expectation."""
        roles = {e["role"]: e for e in
                 checker.check(self.complete, self.manifest,
                               include_planned=True)["planned_roles"]}
        installed = [r for r in self.manifest["character_generator"]["roles"] if r["installed"]]
        for role in installed:
            self.assertTrue(roles[role["role"]]["satisfied"], role["role"])

        victim = installed[0]
        without = json.loads(json.dumps(self.complete))
        field = without["UNETLoader"]["input"]["required"]["unet_name"]
        field[0] = [name for name in field[0] if name != victim["installed"]]
        flipped = {e["role"]: e for e in
                   checker.check(without, self.manifest,
                                 include_planned=True)["planned_roles"]}
        self.assertFalse(flipped[victim["role"]]["satisfied"],
                         "removing the only installed file must flip the role to unmet")

    def test_quantisation_variants_are_not_reported_as_separate_missing_files(self):
        """Listing the variants flat made the checker cry wolf on a ready machine."""
        report = checker.check(self.complete, self.manifest, include_planned=True)
        self.assertEqual({item["file"] for item in report["missing_models"]}, set())
        self.assertEqual(checker.check(self.complete, self.manifest)["planned_roles"], [],
                         "the roles are opt-in")

    def test_any_one_alternative_satisfies_a_role(self):
        for name in ("qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors",
                     "qwen3.5_9b_flux3_prompt_upsampler_bf16.safetensors"):
            with self.subTest(alternative=name):
                inventory = json.loads(json.dumps(self.complete))
                inventory["UNETLoader"]["input"]["required"]["unet_name"] = [[name], {}]
                report = checker.check(inventory, self.manifest, include_planned=True)
                roles = {e["role"]: e for e in report["planned_roles"]}
                self.assertTrue(roles["prompt upsampler"]["satisfied"])
                self.assertEqual(roles["prompt upsampler"]["matched"], [name])

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
