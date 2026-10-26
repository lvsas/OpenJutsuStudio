"""Offline readiness policy: optional extensions are not baseline requirements."""
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dependency_checker_policy", ROOT / "scripts" / "check_dependencies.py")
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)
NATIVE = "h3-native-continuity-experimental"


class CheckerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "comfyui_packs": [
                {"name": "baseline", "nodes": ["Baseline"], "required": True,
                 "used_by": ["swap"]},
                {"name": "native", "nodes": ["Native"], "required": False,
                 "used_by": [NATIVE]},
            ],
            "character_generator": {
                "status": "installed", "used_by": ["characters"],
                "roles": [
                    {"role": "diffusion", "required": True,
                     "alternatives": ["first.safetensors", "second.safetensors"]},
                    {"role": "upsampler", "required": False,
                     "alternatives": ["optional.safetensors"]},
                ],
            },
        }
        self.inventory: dict = {"Baseline": {"python_module": "baseline"}}

    def run_cli(self, *args):
        output = io.StringIO()
        with patch.object(checker, "load_manifest", return_value=self.manifest), \
                patch.object(checker, "fetch_object_info", return_value=self.inventory), \
                contextlib.redirect_stdout(output):
            code = checker.main(["--json", *args])
        return code, json.loads(output.getvalue())

    def test_absent_optional_pack_does_not_fail_baseline(self):
        code, report = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(report["missing_nodes"], {})
        self.assertEqual(report["optional_missing_nodes"]["native"]["missing"], ["Native"])
        self.assertEqual(report["selected_features"], [])
        self.assertEqual(report["planned_roles"], [])

    def test_include_planned_missing_required_character_role_fails(self):
        self.inventory["Native"] = {}
        code, report = self.run_cli("--include-planned")
        self.assertEqual(code, 1)
        self.assertIn("characters", report["selected_features"])
        self.assertFalse(report["planned_roles"][0]["satisfied"])
        self.assertTrue(report["planned_roles"][0]["required"])

    def test_explicit_native_feature_promotes_only_its_optional_packs(self):
        code, report = self.run_cli("--feature", NATIVE)
        self.assertEqual(code, 1)
        self.assertIn("native", report["missing_nodes"])
        self.assertEqual(report["optional_missing_nodes"], {})
        self.assertEqual(report["planned_roles"], [])
        self.inventory["Native"] = {}
        self.assertEqual(self.run_cli("--feature", NATIVE)[0], 0)

    def test_explicit_characters_accepts_one_alternative_not_optional_upsampler(self):
        self.assertEqual(self.run_cli("--feature", "characters")[0], 1)
        self.inventory["UNETLoader"] = {"input": {"required": {
            "unet_name": [["second.safetensors"], {}]}}}
        code, report = self.run_cli("--feature", "characters")
        self.assertEqual(code, 0)
        self.assertEqual(report["planned_roles"][0]["matched"], ["second.safetensors"])
        self.assertFalse(report["planned_roles"][1]["satisfied"])
        self.assertFalse(report["planned_roles"][1]["required"])
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            checker.print_report(report)
        self.assertIn("OPTIONAL", text.getvalue())
        self.assertNotIn("MISSING", text.getvalue())
        self.assertIn("everything required is present", text.getvalue())

    def test_unmet_required_role_never_prints_everything_present(self):
        _, report = self.run_cli("--include-planned")
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            checker.print_report(report)
        self.assertNotIn("everything required is present", text.getvalue())

    def test_feature_selection_is_additive_and_repeatable(self):
        self.inventory.pop("Baseline")
        code, report = self.run_cli("--feature", NATIVE, "--feature", "characters",
                                    "--feature", NATIVE)
        self.assertEqual(code, 1)
        self.assertEqual(set(report["missing_nodes"]), {"baseline", "native"})
        self.assertEqual(report["selected_features"], sorted({NATIVE, "characters"}))

    def test_unknown_feature_is_rejected_before_network_access(self):
        with patch.object(checker, "load_manifest", return_value=self.manifest), \
                patch.object(checker, "fetch_object_info") as fetch, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            checker.main(["--feature", "typo"])
        self.assertEqual(exc.exception.code, 2)
        fetch.assert_not_called()

    def test_planned_entries_are_skipped_unless_include_planned(self):
        self.manifest["comfyui_packs"][1]["status"] = "planned"
        self.manifest["models"] = [{"file": "future.safetensors", "folder": "vae",
                                    "status": "planned"}]
        self.manifest["character_generator"]["status"] = "planned"
        code, report = self.run_cli("--feature", NATIVE, "--feature", "characters")
        self.assertEqual(code, 0)
        self.assertEqual(report["missing_nodes"], {})
        self.assertEqual(report["missing_models"], [])
        self.assertEqual(report["planned_roles"], [])
        self.assertEqual(report["checked_models"], 0)
        code, report = self.run_cli("--feature", NATIVE, "--include-planned")
        self.assertEqual(code, 1)
        self.assertIn("native", report["missing_nodes"])
        self.assertEqual(report["missing_models"][0]["file"], "future.safetensors")
        self.assertTrue(report["planned_roles"])

    def test_planned_role_is_not_checked_by_default_for_selected_characters(self):
        self.manifest["character_generator"]["roles"][0]["status"] = "planned"
        code, report = self.run_cli("--feature", "characters")
        self.assertEqual(code, 0)
        self.assertEqual([role["role"] for role in report["planned_roles"]], ["upsampler"])
        self.assertEqual(self.run_cli("--feature", "characters", "--include-planned")[0], 1)

    def test_missing_builtin_core_node_blocks_readiness(self):
        self.manifest["core_nodes"] = {
            "from_core": ["CoreSampler"], "from_comfy_extras": ["ExtraNode"]}
        self.inventory["ExtraNode"] = {}
        code, report = self.run_cli()
        self.assertEqual(code, 1)
        self.assertEqual(report["missing_core_nodes"], ["CoreSampler"])
        self.inventory["CoreSampler"] = {}
        self.assertEqual(self.run_cli()[0], 0)

    def test_required_pack_without_flag_remains_required(self):
        del self.manifest["comfyui_packs"][0]["required"]
        self.inventory.clear()
        self.assertEqual(self.run_cli()[0], 1)


class CapsulesManifestTests(unittest.TestCase):
    def test_real_manifest_keeps_native_extensions_out_of_baseline_verdict(self):
        manifest = checker.load_manifest()
        inventory = {node: {} for pack in manifest["comfyui_packs"]
                     if pack.get("required", True) for node in pack["nodes"]}
        for group in ("from_core", "from_comfy_extras"):
            inventory.update({node: {} for node in manifest["core_nodes"][group]})
        for entry in manifest["models"] + manifest["loras"]:
            node, field = checker.LOADER_FIELD[entry["folder"]]
            fields = inventory.setdefault(node, {}).setdefault("input", {}).setdefault("required", {})
            fields.setdefault(field, [[], {}])[0].append(entry["file"])
        report = checker.check(inventory, manifest)
        self.assertFalse(checker.required_missing(report))
        native_names = {"comfyui-obvpm", "comfyui-obvpm-timeline", "ComfyUI-OpenJutsu-Capsules"}
        self.assertTrue(native_names <= set(report["optional_missing_nodes"]))
        self.assertIn("ComfyUI-QwenVL", report["optional_missing_nodes"])
        self.assertTrue({"missing_nodes", "present_packs", "missing_models", "missing_core_nodes",
                         "planned_roles", "checked_models"} <= report.keys())
        native = checker.check(inventory, manifest, selected_features=[NATIVE])
        self.assertTrue(checker.required_missing(native))
        self.assertEqual(set(native["missing_nodes"]), native_names)
        self.assertIn("ComfyUI-QwenVL", native["optional_missing_nodes"])
        described = checker.check(inventory, manifest, selected_features=['h3-descriptions'])
        self.assertEqual(set(described['missing_nodes']), {'ComfyUI-QwenVL'})
        for pack in manifest["comfyui_packs"]:
            inventory.update({node: {} for node in pack["nodes"] if node not in inventory})
        self.assertFalse(checker.required_missing(checker.check(
            inventory, manifest, selected_features=[NATIVE])))

    def test_native_publisher_and_restager_have_verified_source_and_pin(self):
        manifest = checker.load_manifest()
        packs = [pack for pack in manifest["comfyui_packs"]
                 if pack["name"] == "ComfyUI-OpenJutsu-Capsules"]
        self.assertEqual(len(packs), 1)
        pack = packs[0]
        self.assertEqual(pack["source"], "https://github.com/lvsas/ComfyUI-OpenJutsu-Capsules")
        self.assertEqual(pack["pin"], "7288a04bbdde5cd793d0ec38c4de3c49a33840d0")
        self.assertFalse(pack["required"])
        self.assertIn(NATIVE, pack["used_by"])
        self.assertNotIn("h3-recast", pack["used_by"])
        for node, source in (
            ("OpenGenjutsuH3PublishClip", "src/h3_continuity_graphs.py"),
            ("OpenGenjutsuH3RestageFamily", "src/h3_family_graphs.py"),
        ):
            with self.subTest(node=node):
                self.assertIn(node, (ROOT / source).read_text())
                self.assertIn(node, pack["nodes"])
                self.assertIn(node, (ROOT / "custom_nodes/opengenjutsu_continuity/__init__.py").read_text())
        # A source pin is documented provenance, not something /object_info can verify.
        evidence = (ROOT / "docs/validation/2026-10-22-restage-suffix-regression.md").read_text()
        self.assertIn(pack["pin"], evidence)


if __name__ == "__main__":
    unittest.main()
