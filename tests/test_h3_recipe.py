"""Aspect-aware H3 recipe sizing; fixtures are synthetic dimensions only."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from h3_recipe import (REFERENCE_SLOTS, h3_dimensions, make_recipe, validate_recipe,
                       with_preserve_clip)


class H3DimensionsTests(unittest.TestCase):
    def test_common_aspects_are_derived_not_fixed_to_landscape(self):
        # Input canvas = half the 0.9 MP aspect-aware output canvas, on H3's 32 grid.
        cases = [
            ((1920, 1080), (640, 352), (1280, 704)),
            ((1080, 1920), (352, 640), (704, 1280)),
            ((1080, 1080), (480, 480), (960, 960)),
            ((1440, 1080), (544, 416), (1088, 832)),
            ((1200, 500), (736, 320), (1472, 640)),
        ]
        for source, expected_input, expected_output in cases:
            with self.subTest(source=source):
                self.assertEqual(h3_dimensions(*source), expected_input)
                recipe = make_recipe(source_width=source[0], source_height=source[1])
                self.assertEqual((recipe["output_width"], recipe["output_height"]), expected_output)
                for side in (*expected_input, *expected_output):
                    self.assertEqual(side % 32, 0)
                # Every aspect lands near the shared 0.9 MP target.
                self.assertAlmostEqual(expected_output[0] * expected_output[1] / 1e6, 0.9, delta=0.05)

    def test_recipe_freezes_source_derived_dimensions(self):
        portrait = make_recipe(source_width=1080, source_height=1920)
        self.assertEqual((portrait["width"], portrait["height"]), (352, 640))
        self.assertEqual((portrait["output_width"], portrait["output_height"]), (704, 1280))
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

    V2_PROMPT_FOR_ONE_REFERENCE = (
        "<Subject 1> is the replacement character whose appearance is shown in <Picture 1>: "
        "a tall woman in a red coat.\n"
        "<Video 1> supplies the source performance, scene, framing, timing and camera motion.\n"
        "Replace only the main performer in <Video 1> with <Subject 1>. Keep the original "
        "performance, poses, gestures, framing, environment, camera movement and lighting from "
        "<Video 1>. Use <Picture 1> only for the replacement character's identity, build and "
        "clothing; do not reproduce its layout, background, extra poses or props. Do not invent "
        "actions, people, cuts or objects. Preserve the source soundtrack and keep the replacement "
        "stable throughout the shot."
    )

    def test_policy_v3_keeps_the_winning_single_reference_prompt_byte_for_byte(self):
        recipe = make_recipe(source_width=1920, source_height=1080,
                             reference_descriptions=("a tall woman in a red coat",))
        self.assertEqual((recipe["schema_version"], recipe["prompt_policy"]), (3, "h3-recast-v3"))
        self.assertEqual(recipe["effective_prompt"], self.V2_PROMPT_FOR_ONE_REFERENCE)
        self.assertEqual(recipe["reference_count"], 1)
        self.assertEqual(recipe["reference_description_sources"], ["user"])
        validate_recipe(recipe)

    def test_two_references_extend_the_scaffold_and_carry_provenance(self):
        recipe = make_recipe(source_width=1920, source_height=1080,
                             reference_descriptions=("a tall woman in a red coat", "a small dog"),
                             reference_sources=("user", "generated"))
        prompt = recipe["effective_prompt"]
        self.assertIn("<Picture 1>: a tall woman in a red coat.", prompt)
        self.assertIn("<Picture 2>: a small dog.", prompt)
        self.assertIn("Replace only the main performers in <Video 1> with <Subject 1> and <Subject 2>.", prompt)
        self.assertEqual(recipe["reference_description_sources"], ["user", "generated"])
        validate_recipe(recipe)

    def test_generated_preservation_is_frozen_with_its_provenance(self):
        recipe = make_recipe(source_width=1920, source_height=1080,
                             reference_descriptions=('a tall woman',))
        self.assertEqual((recipe['preserve_clip'], recipe['preserve_clip_source']), ('', 'none'))
        self.assertNotIn('Additional directions', recipe['effective_prompt'])
        completed = with_preserve_clip(recipe, 'the wooden staff and the snowy valley')
        self.assertEqual(completed['preserve_clip_source'], 'generated')
        self.assertTrue(completed['effective_prompt'].endswith(
            'Additional directions: the wooden staff and the snowy valley'))
        self.assertEqual(completed['reference_descriptions'], ['a tall woman'])
        validate_recipe(completed)
        authored = make_recipe(preserve_clip='keep the scarf', source_width=1920, source_height=1080)
        self.assertEqual(authored['preserve_clip_source'], 'user')
        with self.assertRaises(ValueError):
            with_preserve_clip(authored, 'something else')
        broken = copy.deepcopy(recipe)
        broken['preserve_clip'] = 'text without a provenance'
        with self.assertRaises(ValueError):
            validate_recipe(broken)
        for bad in ({'preserve_clip': 'x', 'preserve_clip_source': 'none'},
                    {'preserve_clip': 'x', 'preserve_clip_source': 'invented'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                make_recipe(source_width=1920, source_height=1080, **bad)

    def test_capacity_is_shared_across_graph_recipe_and_api(self):
        from h3_graphs import REFERENCE_SLOTS as graph_slots
        self.assertEqual(REFERENCE_SLOTS, graph_slots)
        self.assertEqual(REFERENCE_SLOTS, 2)
        recipe = make_recipe(source_width=1920, source_height=1080,
                             reference_descriptions=('one', 'two'))
        self.assertEqual(recipe['reference_count'], 2)
        with self.assertRaises(ValueError):
            make_recipe(source_width=1920, source_height=1080,
                        reference_descriptions=('one', 'two', 'three'))

    def test_legacy_policy_mismatched_prompt_and_oversized_text_are_rejected(self):
        recipe = make_recipe(source_width=1920, source_height=1080)
        for field, value in (("prompt_policy", "h3-recast-v2"), ("schema_version", 2),
                             ("effective_prompt", "Replace the main performer in <Video 1>."),
                             ("reference_description_sources", ["invented"])):
            broken = copy.deepcopy(recipe)
            broken[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_recipe(broken)
        for kwargs in ({"reference_descriptions": ("x" * 2001,)}, {"preserve_clip": "x" * 2001},
                       {"reference_descriptions": ("a", "b", "c")}, {"reference_descriptions": ()},
                       {"reference_descriptions": ("a",), "reference_sources": ("user", "generated")},
                       {"reference_descriptions": ("a",), "reference_sources": ("guessed",)}):
            with self.subTest(kwargs=list(kwargs)), self.assertRaises(ValueError):
                make_recipe(source_width=1920, source_height=1080, **kwargs)


if __name__ == "__main__":
    unittest.main()