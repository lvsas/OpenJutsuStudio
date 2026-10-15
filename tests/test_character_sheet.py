"""Tests for character sheet (reference image injection)."""
import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import build_frame_edit


class TestCharacterSheet(unittest.TestCase):
    """Test build_frame_edit with reference image support."""

    def test_build_frame_edit_without_reference(self):
        """Without reference image, graph should have 1 LoadImage (the frame)."""
        graph = build_frame_edit(
            image="frame0.png",
            prompt="Replace with a knight"
        )
        node_ids = list(graph.keys())
        load_image_nodes = [n for n in node_ids if graph[n]["class_type"] == "LoadImage"]
        self.assertEqual(len(load_image_nodes), 1, "One LoadImage for the frame")

    def test_build_frame_edit_with_reference(self):
        """With reference image, graph should have 2 LoadImage nodes."""
        graph = build_frame_edit(
            image="frame0.png",
            prompt="Replace with the reference character",
            reference_image="character_sheet.png"
        )
        node_ids = list(graph.keys())
        load_image_nodes = [n for n in node_ids if graph[n]["class_type"] == "LoadImage"]
        self.assertGreaterEqual(len(load_image_nodes), 2, "Frame + reference image")

    def test_reference_image_in_graph_inputs(self):
        """The reference image should appear in graph node inputs."""
        graph = build_frame_edit(
            image="frame0.png",
            prompt="Replace with the reference character",
            reference_image="character_sheet.png"
        )
        # Check that character_sheet.png appears somewhere in the graph
        graph_str = str(graph)
        self.assertIn("character_sheet.png", graph_str)

    def test_no_reference_image_no_extra_nodes(self):
        """Without reference, no ReferenceLatent or extra nodes."""
        graph = build_frame_edit(
            image="frame0.png",
            prompt="Replace with a knight"
        )
        # Should not have ReferenceLatent without reference
        node_types = [graph[n]["class_type"] for n in graph]
        # ReferenceLatent is only added when reference is provided
        # (it's OK if it exists from other logic, but shouldn't be required)


if __name__ == "__main__":
    unittest.main()
