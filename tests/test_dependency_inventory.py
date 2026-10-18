"""The dependency inventory is only useful while it is true, so it is checked.

Any node class or model file that a workflow starts referencing must appear in
`docs/dependencies.md`. Without this, a new node silently becomes an undocumented requirement and
the install guide a third party follows stops working.
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "dependencies.md"
FIELD_PREFIXES = ("unet_name", "vae_name", "clip_name", "lora_name", "ckpt_name")
MODEL_SUFFIXES = (".safetensors", ".gguf", ".pth", ".bin", ".ckpt")


def _workflow_files():
    return sorted((ROOT / "workflows").glob("*.json"))


def _api_graphs():
    return [json.loads(path.read_text()) for path in _workflow_files()]


def used_node_classes():
    classes = set()
    for graph in _api_graphs():
        for node in graph.values():
            if isinstance(node, dict) and "class_type" in node:
                classes.add(node["class_type"])
    source = (ROOT / "src" / "h3_graphs.py").read_text()
    classes.update(re.findall(r'class_type["\']?\s*[:=]\s*["\']([A-Za-z0-9_ ()]+)["\']', source))
    return classes


def used_models():
    names = set()
    for graph in _api_graphs():
        for node in graph.values():
            if not isinstance(node, dict):
                continue
            for field, value in (node.get("inputs") or {}).items():
                if field.startswith(FIELD_PREFIXES) and isinstance(value, str):
                    names.add(value)
    source = (ROOT / "src" / "h3_graphs.py").read_text()
    names.update(name for name in re.findall(r'["\']([A-Za-z0-9_\-./ ]+)["\']', source)
                 if name.endswith(MODEL_SUFFIXES))
    return names


class DependencyInventoryTests(unittest.TestCase):
    def setUp(self):
        self.document = DOC.read_text()

    def test_the_inventory_document_exists(self):
        self.assertTrue(DOC.is_file(), "docs/dependencies.md is missing")

    def test_every_node_class_a_workflow_uses_is_documented(self):
        for name in sorted(used_node_classes()):
            with self.subTest(node=name):
                self.assertIn(name, self.document,
                              f"{name} is used by a workflow but absent from docs/dependencies.md")

    def test_every_model_a_workflow_names_is_documented(self):
        for name in sorted(used_models()):
            with self.subTest(model=name):
                self.assertIn(name, self.document,
                              f"{name} is named by a workflow but absent from docs/dependencies.md")

    def test_the_upstream_pack_names_are_recorded(self):
        """A bundled local folder is not an installable dependency; the upstream names are."""
        for pack in ("ComfyUI-VideoHelperSuite", "ComfyUI-LTXVideo", "ComfyUI-KJNodes",
                     "ComfyUI_Res4lyf", "MiniMaxH3-LatentUpscaler"):
            with self.subTest(pack=pack):
                self.assertIn(pack, self.document)

    def test_the_document_names_the_proxy_default_that_is_not_running(self):
        """The default Comfy target points at a loopback proxy; a reader must be told."""
        self.assertIn("8189", self.document)


if __name__ == "__main__":
    unittest.main()
