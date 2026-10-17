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

    def test_prompt_policy_v2_scaffold_and_user_owned_description(self):
        plain = make_recipe(source_width=1920, source_height=1080)
        self.assertEqual((plain["schema_version"], plain["prompt_policy"]), (2, "h3-recast-v2"))
        for role in ("<Subject 1>", "<Picture 1>", "<Video 1>"):
            self.assertIn(role, plain["effective_prompt"])
        for rule in ("Replace only the main performer", "Do not invent", "Preserve the source soundtrack"):
            self.assertIn(rule, plain["effective_prompt"])
        self.assertNotIn(": .", plain["effective_prompt"])
        described = make_recipe(source_width=1920, source_height=1080,
                               character_description="a tall woman in a red coat")
        self.assertIn("shown in <Picture 1>: a tall woman in a red coat.", described["effective_prompt"])
        self.assertNotEqual(plain["effective_prompt"], described["effective_prompt"])
        self.assertEqual(described["character_description"], "a tall woman in a red coat")
        # Directions stay separate from the character description.
        directed = make_recipe("keep the wooden staff", source_width=1920, source_height=1080,
                               character_description="a tall woman in a red coat")
        self.assertTrue(directed["effective_prompt"].endswith("Additional directions: keep the wooden staff"))

    def test_legacy_policy_and_oversized_text_are_rejected(self):
        recipe = make_recipe(source_width=1920, source_height=1080)
        legacy = copy.deepcopy(recipe)
        legacy["prompt_policy"] = "h3-recast-v1"
        with self.assertRaises(ValueError):
            validate_recipe(legacy)
        tampered = copy.deepcopy(recipe)
        tampered["effective_prompt"] = "Replace the main performer in <Video 1>."
        with self.assertRaises(ValueError):
            validate_recipe(tampered)
        for field in ("character_description", "edit_prompt"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                make_recipe(source_width=1920, source_height=1080, **{field: "x" * 2001})


if __name__ == "__main__":
    unittest.main()
