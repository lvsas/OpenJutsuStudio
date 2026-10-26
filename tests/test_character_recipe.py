"""Recipe contract for the FLUX 3 Viral Character Maker."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tests.character_recipe_fixtures import v1_recipe_fixture, v2_recipe_fixture  # noqa: E402
from character_recipe import (  # noqa: E402
    AXES,
    ENGINE,
    MODE_SPECS,
    MODEL_ROLES,
    TREND_LIBRARY,
    digest_json,
    make_recipe,
    validate_recipe,
)


class CharacterRecipeTests(unittest.TestCase):
    def setUp(self):
        self.recipe = make_recipe(
            job_id="character_recipe_1",
            direction="an original heavyweight beekeeper with a deliberately blunt bowl cut",
            mode="portrait",
            trend_id="original",
            selections={"skin_tone": "fair skin", "hair": "short blunt bowl cut"},
            sampler_seed=758781618552631,
            upsampler_seed=758781618552631,
            upsampler=True,
        )

    def test_new_generated_recipes_are_v6_weird_humans_and_reject_v1_only_accessory(self):
        self.assertEqual(self.recipe["schema_version"], 6)
        self.assertEqual(self.recipe["prompt_policy"], "character-v6")
        self.assertIs(self.recipe["face_refine"], False)
        self.assertEqual(self.recipe["direction_origin"], "generated")
        self.assertIn("no hand-held or carried props", self.recipe["resolved_request"])
        self.assertNotIn("accessory", self.recipe["selections"])
        self.assertNotIn("absurdity", self.recipe["selections"])
        with self.assertRaisesRegex(ValueError, "Unknown Character selection axis"):
            make_recipe(job_id="character_no_accessory", direction="an original performer", mode="portrait",
                        trend_id="original", selections={"accessory": "a chrome accordion"},
                        sampler_seed=1, upsampler_seed=2, upsampler=True)

    def test_user_authored_direction_can_explicitly_use_a_prop_without_default_policy_override(self):
        recipe = make_recipe(
            job_id="character_user_prop", direction="an original locksmith holding one brass key",
            mode="portrait", trend_id="original", selections={}, sampler_seed=2, upsampler_seed=3,
            upsampler=True, direction_origin="user_authored")
        self.assertEqual(recipe["direction_origin"], "user_authored")
        self.assertIn("holding one brass key", recipe["resolved_request"])
        self.assertNotIn("no held, carried, worn, or visible props; no object in the hands or on the body",
                         recipe["resolved_request"])
        with self.assertRaisesRegex(ValueError, "direction origin"):
            make_recipe(job_id="character_bad_origin", direction="an original performer", mode="portrait",
                        trend_id="original", selections={}, sampler_seed=1, upsampler_seed=2, upsampler=True,
                        direction_origin="system")

    def test_v1_and_v2_recipe_evidence_remain_exactly_readable_without_coercion_to_v3(self):
        legacy = v1_recipe_fixture()
        self.assertEqual(validate_recipe(legacy), legacy)
        self.assertEqual(validate_recipe(legacy)["schema_version"], 1)
        self.assertEqual(validate_recipe(legacy)["prompt_policy"], "character-v1")
        self.assertEqual(validate_recipe(legacy)["selections"]["accessory"], "a folded paper map")
        v2 = v2_recipe_fixture()
        self.assertEqual(validate_recipe(v2), v2)
        self.assertEqual(validate_recipe(v2)["schema_version"], 2)
        self.assertEqual(validate_recipe(v2)["prompt_policy"], "character-v2")
        self.assertNotIn("direction_origin", validate_recipe(v2))

    def test_recipe_freezes_all_resolved_generation_facts(self):
        self.assertEqual(self.recipe["engine"], ENGINE)
        self.assertEqual(self.recipe["mode"], "portrait")
        self.assertEqual(self.recipe["aspect_ratio"], MODE_SPECS["portrait"]["aspect_ratio"])
        self.assertEqual(self.recipe["trend_id"], "original")
        self.assertEqual(self.recipe["raw_direction"],
                         "an original heavyweight beekeeper with a deliberately blunt bowl cut")
        self.assertEqual(self.recipe["selections"]["skin_tone"], "fair skin")
        self.assertEqual(self.recipe["selections"]["hair"], "short blunt bowl cut")
        for axis in set(AXES) - {"skin_tone", "hair"}:
            self.assertEqual(self.recipe["selections"][axis], "model_decides")
        self.assertEqual(self.recipe["sampler_seed"], self.recipe["upsampler_seed"])
        self.assertEqual(self.recipe["model_roles"], MODEL_ROLES)
        self.assertRegex(self.recipe["vendor_workflow_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(self.recipe["system_prompt_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(self.recipe["graph_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(self.recipe["graph_sha256"], digest_json(self.recipe["graph_template"]))
        encoded = json.dumps(self.recipe, sort_keys=True)
        self.assertNotIn("/home/", encoded)
        self.assertNotIn("127.0.0.1", encoded)
        validate_recipe(self.recipe)

    def test_request_is_photographic_and_turnaround_asks_for_four_different_angles(self):
        self.assertTrue(self.recipe["resolved_request"].startswith("Full-length photograph"))
        turnaround = make_recipe(
            job_id="character_turnaround_1", direction="an original locksmith", mode="turnaround",
            trend_id="original", selections={}, sampler_seed=1, upsampler_seed=1, upsampler=True)
        request = turnaround["resolved_request"]
        self.assertTrue(request.startswith("Studio photographic quadriptych"))
        self.assertNotIn("character sheet", request.lower())
        # The earlier probe asked for "four identical views", which is why every panel came back
        # frontal. A usable turnaround must name the four distinct angles.
        self.assertNotIn("identical views", request.lower())
        for angle in ("front view", "three-quarter view", "left profile", "back view"):
            with self.subTest(angle=angle):
                self.assertIn(angle, request)
        for negative in ("no text", "no watermark", "exactly one person",
                         "clear eyes", "coherent facial anatomy", "natural adult head-to-body scale"):
            with self.subTest(negative=negative):
                self.assertIn(negative, request)
        with self.assertRaisesRegex(ValueError, "character sheet"):
            make_recipe(job_id="character_bad", direction="a character sheet of a locksmith", mode="portrait",
                        trend_id="original", selections={}, sampler_seed=1, upsampler_seed=1, upsampler=True)

    def test_sampler_and_upsampler_seeds_are_independently_frozen(self):
        independent = make_recipe(
            job_id="character_seeds_1", direction="an original performer", mode="portrait",
            trend_id="original", selections={}, sampler_seed=11, upsampler_seed=29, upsampler=True)
        self.assertEqual(independent["sampler_seed"], 11)
        self.assertEqual(independent["upsampler_seed"], 29)
        self.assertEqual(independent["graph_template"]["18:7"]["inputs"]["seed"], 11)
        self.assertEqual(independent["graph_template"]["18:11"]["inputs"]["sampling_mode.seed"], 29)

    def test_recipe_is_canonical_and_rejects_drift_or_untrusted_controls(self):
        reordered = dict(reversed(list(self.recipe.items())))
        self.assertEqual(digest_json(self.recipe), digest_json(reordered))
        for changed in (
            {"mode": "square"},
            {"trend_id": "unknown"},
            {"sampler_seed": -1},
            {"upsampler": "yes"},
            {"selections": {"unknown_axis": "x"}},
            {"selections": {"hair": "/home/user/file"}},
            {"graph_sha256": "0" * 64},
        ):
            broken = copy.deepcopy(self.recipe)
            broken.update(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_recipe(broken)

    def test_paths_and_private_endpoints_are_rejected_in_every_text_field(self):
        for direction, selections in (
            ("C:/Users/a/secret.txt", {}),
            ("relative/secret.txt", {}),
            ("[::1] original performer", {}),
            ("an original performer", {"hair": "C:/Users/a/secret.txt"}),
            ("an original performer", {"hair": "relative/secret.txt"}),
            ("an original performer", {"hair": "[::1]"}),
        ):
            with self.subTest(direction=direction, selections=selections), self.assertRaises(ValueError):
                make_recipe(job_id="character_unsafe", direction=direction, mode="portrait",
                            trend_id="original", selections=selections, sampler_seed=1,
                            upsampler_seed=2, upsampler=True)

    def test_malformed_mode_and_trend_json_values_raise_validation_errors(self):
        for mode, trend_id in (([], "original"), ({}, "original"), ("portrait", []), ("portrait", {})):
            with self.subTest(mode=mode, trend_id=trend_id), self.assertRaises(ValueError):
                make_recipe(job_id="character_malformed", direction="an original performer", mode=mode,
                            trend_id=trend_id, selections={}, sampler_seed=1, upsampler_seed=2,
                            upsampler=True)

    def test_ordinary_prose_with_a_colon_is_not_mistaken_for_a_windows_path(self):
        """A bare `[A-Za-z]:` check refused any sentence containing 'word:' — including every
        shuffle proposal, which made generation impossible with a 422."""
        for direction in ("An original character: a locksmith with a blunt bowl cut",
                          "An original character: a lighthouse keeper, deeply unimpressed"):
            with self.subTest(direction=direction):
                recipe = make_recipe(job_id="character_prose", direction=direction, mode="portrait",
                                     trend_id="original", selections={}, sampler_seed=1,
                                     upsampler_seed=2, upsampler=True)
                self.assertIn(direction, recipe["resolved_request"])
        for direction in ("C:/Users/a/secret.txt", "C:\\Users\\a\\secret.txt",
                          "read /etc/passwd now", "relative/secret.txt", "../escape"):
            with self.subTest(direction=direction), self.assertRaises(ValueError):
                make_recipe(job_id="character_path", direction=direction, mode="portrait",
                            trend_id="original", selections={}, sampler_seed=1, upsampler_seed=2,
                            upsampler=True)

    def test_v2_keeps_safe_free_text_axes_open_but_rejects_accessory_steering(self):
        free = make_recipe(
            job_id="character_free_1", direction="an original performer", mode="portrait",
            trend_id="original", selections={"attitude": "quietly delighted by a private joke"},
            sampler_seed=9, upsampler_seed=9, upsampler=False)
        self.assertEqual(free["selections"]["attitude"], "quietly delighted by a private joke")
        self.assertEqual(set(TREND_LIBRARY), {"original"})
        self.assertIn("attitude: quietly delighted by a private joke", free["resolved_request"])
        with self.assertRaisesRegex(ValueError, "Unknown Character selection axis"):
            make_recipe(job_id="character_no_prop", direction="an original performer", mode="portrait",
                        trend_id="original", selections={"accessory": "a chrome accordion shaped like a fish"},
                        sampler_seed=9, upsampler_seed=9, upsampler=False)


if __name__ == "__main__":
    unittest.main()
