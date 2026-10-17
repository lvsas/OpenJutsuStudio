"""Aspect-aware H3 recipe sizing; fixtures are synthetic dimensions only."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from h3_recipe import h3_dimensions, make_recipe, validate_recipe


class H3DimensionsTests(unittest.TestCase):
    def test_common_aspects_are_derived_not_fixed_to_landscape(self):
        cases = [
            ((1920, 1080), (512, 288)),
            ((1080, 1920), (288, 512)),
            ((1080, 1080), (512, 512)),
            ((1440, 1080), (512, 384)),
            ((1200, 500), (384, 160)),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(h3_dimensions(*source), expected)
                w, h = expected
                self.assertLessEqual(abs((w / h) / (source[0] / source[1]) - 1), 0.05)

    def test_recipe_freezes_source_derived_dimensions(self):
        portrait = make_recipe(source_width=1080, source_height=1920)
        self.assertEqual((portrait["width"], portrait["height"]), (288, 512))
        self.assertEqual((portrait["output_width"], portrait["output_height"]), (576, 1024))
        self.assertEqual((portrait["source_width"], portrait["source_height"]), (1080, 1920))
        validate_recipe(portrait)
        changed = copy.deepcopy(portrait)
        changed["output_width"] = 1024
        with self.assertRaises(ValueError):
            validate_recipe(changed)

    def test_invalid_or_unrepresentable_dimensions_are_rejected(self):
        for dimensions in ((0, 100), (-1, 100), (True, 100), (900, 10)):
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                h3_dimensions(*dimensions)


if __name__ == "__main__":
    unittest.main()
