"""The Character graph adapter guards the vendor FLUX 3 graph against drift.

This is deliberately stricter than a test that merely posts valid JSON. The product never builds a
FLUX 3 graph from memory: the 19-node vendor file is the topology contract. Runtime may only patch
an explicitly enumerated set of widgets and may append one SaveText output for SDK retrieval.
"""
import copy
import inspect
import ipaddress
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from character_graphs import (  # noqa: E402
    ASPECT_RATIOS,
    IMAGE_OUTPUT_NODE,
    LOCAL_UNET,
    TEXT_OUTPUT_NODE,
    VENDOR_WORKFLOW_PATH,
    VENDOR_WORKFLOW_SHA256,
    build_character_graph,
    load_vendor_graph,
    validate_vendor_workflow,
    workflow_sha256,
)


class CharacterGraphContractTests(unittest.TestCase):
    def setUp(self):
        self.vendor = load_vendor_graph()
        self.graph = build_character_graph(
            request="studio photograph of a bowl-cut heavyweight beekeeper",
            seed=758781618552631,
            aspect_ratio="3:4 (Portrait Standard)",
            upsampler=True,
            job_id="character_abc123",
        )

    def test_vendor_file_is_the_immutable_nineteen_node_contract(self):
        self.assertEqual(VENDOR_WORKFLOW_PATH, ROOT / "workflows" / "flux3-klein-official-t2i.json")
        self.assertEqual(len(self.vendor), 19)
        self.assertEqual(self.vendor["18:11"]["class_type"], "TextGenerate")
        self.assertEqual(self.vendor["18:16"]["class_type"], "ComfySwitchNode")
        self.assertEqual(self.vendor["18:4"]["inputs"]["text"], ["18:13", 0])
        self.assertEqual(self.vendor["18:7"]["class_type"], "KSampler")
        self.assertEqual(self.vendor["19"]["class_type"], "ResolutionSelector")
        self.assertEqual(self.vendor["25"]["class_type"], "CreateBoundingBoxes")
        self.assertEqual(self.vendor["27"]["inputs"]["element"], ["25", 2])
        self.assertEqual(self.vendor["26"]["inputs"]["source"], ["27", 0])
        self.assertEqual(workflow_sha256(self.vendor), VENDOR_WORKFLOW_SHA256)

    def test_vendor_content_or_required_inputs_cannot_drift_silently(self):
        changed = copy.deepcopy(self.vendor)
        changed["18:7"]["inputs"]["steps"] += 1
        with self.assertRaisesRegex(RuntimeError, "content drifted"):
            validate_vendor_workflow(changed)
        malformed = copy.deepcopy(self.vendor)
        del malformed["18:1"]["inputs"]["unet_name"]
        with self.assertRaisesRegex(RuntimeError, "lost runtime input"):
            validate_vendor_workflow(malformed)

    def test_adapter_preserves_every_vendor_node_except_explicit_controls(self):
        allowed = {
            "18:17": {"value"}, "18:1": {"unet_name"}, "19": {"aspect_ratio"},
            "18:16": {"switch"}, "18:7": {"seed"},
            "18:11": {"sampling_mode.seed"}, "9": {"filename_prefix"},
        }
        self.assertEqual(set(self.graph), set(self.vendor) | {TEXT_OUTPUT_NODE})
        for node_id, vendor_node in self.vendor.items():
            normalized = copy.deepcopy(self.graph[node_id])
            for field in allowed.get(node_id, set()):
                normalized["inputs"][field] = vendor_node["inputs"][field]
            self.assertEqual(normalized, vendor_node,
                             f"{node_id} changed outside the declared runtime controls")

    def test_adapter_patches_only_the_declared_runtime_controls(self):
        self.assertEqual(self.graph["18:17"]["inputs"]["value"],
                         "studio photograph of a bowl-cut heavyweight beekeeper")
        self.assertEqual(self.graph["18:1"]["inputs"]["unet_name"], LOCAL_UNET)
        self.assertEqual(self.graph["19"]["inputs"]["aspect_ratio"], "3:4 (Portrait Standard)")
        self.assertTrue(self.graph["18:16"]["inputs"]["switch"])
        self.assertEqual(self.graph["18:7"]["inputs"]["seed"], 758781618552631)
        self.assertEqual(self.graph["18:11"]["inputs"]["sampling_mode.seed"], 758781618552631)
        self.assertEqual(self.graph["9"]["inputs"]["filename_prefix"],
                         "OpenGenjutsu/characters/character_abc123/image")

    def test_saved_caption_is_an_explicit_second_output(self):
        text = self.graph[TEXT_OUTPUT_NODE]
        self.assertEqual(text["class_type"], "SaveText")
        self.assertEqual(text["inputs"], {
            "text": ["18:13", 0],
            "filename_prefix": "OpenGenjutsu/characters/character_abc123/caption",
            "format": "txt",
        })
        self.assertEqual(IMAGE_OUTPUT_NODE, "9")

    def test_vendor_template_is_never_mutated(self):
        before = copy.deepcopy(self.vendor)
        build_character_graph("another request", 12, "16:9 (Widescreen)", False, "character_other")
        self.assertEqual(self.vendor, before)
        self.assertEqual(load_vendor_graph(), before)

    def test_rejects_malformed_controls_before_a_submission_exists(self):
        cases = [
            ("", 1, "3:4 (Portrait Standard)", True, "character_ok"),
            ("   ", 1, "3:4 (Portrait Standard)", True, "character_ok"),
            (None, 1, "3:4 (Portrait Standard)", True, "character_ok"),
            ("x" * 2_001, 1, "3:4 (Portrait Standard)", True, "character_ok"),
            ("x", -1, "3:4 (Portrait Standard)", True, "character_ok"),
            ("x", True, "3:4 (Portrait Standard)", True, "character_ok"),
            ("x", 1.0, "3:4 (Portrait Standard)", True, "character_ok"),
            ("x", 2**64, "3:4 (Portrait Standard)", True, "character_ok"),
            ("x", 1, "not-a-ratio", True, "character_ok"),
            ("x", 1, None, True, "character_ok"),
            ("x", 1, "3:4 (Portrait Standard)", "true", "character_ok"),
            ("x", 1, "3:4 (Portrait Standard)", 1, "character_ok"),
            ("x", 1, "3:4 (Portrait Standard)", True, ""),
            ("x", 1, "3:4 (Portrait Standard)", True, None),
            ("x", 1, "3:4 (Portrait Standard)", True, "x" * 129),
            ("x", 1, "3:4 (Portrait Standard)", True, "../../escape"),
        ]
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    build_character_graph(*args)

    def test_filename_prefix_is_not_a_browser_control(self):
        parameters = inspect.signature(build_character_graph).parameters
        self.assertNotIn("filename_prefix", parameters)
        self.assertNotIn("prefix", parameters)
        self.assertEqual(
            self.graph[IMAGE_OUTPUT_NODE]["inputs"]["filename_prefix"],
            "OpenGenjutsu/characters/character_abc123/image",
        )
        self.assertEqual(
            self.graph[TEXT_OUTPUT_NODE]["inputs"]["filename_prefix"],
            "OpenGenjutsu/characters/character_abc123/caption",
        )

    def test_every_supported_ratio_contains_the_vendor_default(self):
        """API exports retain the selected literal, not the ResolutionSelector COMBO choices."""
        vendor_default = self.vendor["19"]["inputs"]["aspect_ratio"]
        self.assertIn(vendor_default, ASPECT_RATIOS)
        self.assertIn("3:4 (Portrait Standard)", ASPECT_RATIOS)
        self.assertIn("16:9 (Widescreen)", ASPECT_RATIOS)

    def test_canonical_digest_is_order_independent_and_content_sensitive(self):
        reordered = dict(reversed(list(self.graph.items())))
        self.assertEqual(workflow_sha256(self.graph), workflow_sha256(reordered))
        changed = copy.deepcopy(self.graph)
        changed["18:17"]["inputs"]["value"] = "a different original character"
        self.assertNotEqual(workflow_sha256(self.graph), workflow_sha256(changed))

    def test_graph_and_digest_carry_no_local_path_or_private_address(self):
        encoded = json.dumps(self.graph, sort_keys=True)
        self.assertNotRegex(encoded, r'"/(?:home|etc|tmp|var)/')
        self.assertNotIn("file://", encoded)
        self.assertNotRegex(encoded, r"[A-Za-z]:\\\\")
        self.assertNotIn("localhost", encoded.lower())
        for candidate in re.findall(r"(?:https?://)?(?:\d{1,3}\.){3}\d{1,3}", encoded):
            address = ipaddress.ip_address(candidate.removeprefix("http://").removeprefix("https://"))
            self.assertFalse(address.is_private or address.is_loopback,
                             f"private/system address leaked into graph: {address}")
        self.assertRegex(workflow_sha256(self.graph), r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
