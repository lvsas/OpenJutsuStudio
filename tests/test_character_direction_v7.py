"""V7 semantic construction, strict snapshot, and immutable historical evidence."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from character_recipe import make_recipe, validate_recipe, validate_current_recipe
from tests.character_recipe_fixtures import v1_recipe_fixture, v2_recipe_fixture

FACTS = {
    "being": "woman", "role": "architect", "build": "a broad powerful build",
    "hair": "enormous sculptural silver hair", "face": "a square jaw and clear green eyes",
    "outfit": "a tailored navy wool suit", "attitude": "quietly amused with an upright stance",
    "primary_axis": "hair",
}


def wording(facts):
    article = "an" if facts["role"][0].lower() in "aeiou" else "a"
    return (f"An original adult {facts['being']}, {article} {facts['role']}: {facts['build']}, "
            f"{facts['hair']}, {facts['face']}, wearing {facts['outfit']}, {facts['attitude']}.")


def recipe(**changes):
    params = dict(job_id="direction_v7", direction=wording(FACTS), direction_facts=copy.deepcopy(FACTS),
                  direction_origin="generated", mode="portrait", trend_id="original", selections={},
                  sampler_seed=11, upsampler_seed=29, upsampler=False)
    return make_recipe(**(params | changes))


class CharacterDirectionV7Tests(unittest.TestCase):
    def test_refinements_replace_facts_before_caption_and_preserve_inputs(self):
        facts = copy.deepcopy(FACTS)
        replacements = {"being": "man", "role": "opera singer", "build": "a compact wiry build",
                        "hair": "a giant black geometric pompadour", "face": "a long face with blue eyes",
                        "outfit": "a scarlet velvet jacket", "attitude": "openly delighted",
                        "skin_tone": "warm brown skin", "era": "the nineteen seventies"}
        before = copy.deepcopy(replacements)
        r = recipe(direction_facts=facts, selections=replacements)
        self.assertEqual((r["schema_version"], r["prompt_policy"]), (7, "character-v7"))
        self.assertEqual(r["raw_direction"], wording(FACTS))
        self.assertEqual(r["direction_facts"], FACTS)
        self.assertEqual(r["selections"], replacements)
        text = r["resolved_request"]
        for axis in ("being", "role", "build", "hair", "face", "outfit", "attitude"):
            with self.subTest(axis=axis):
                self.assertNotIn(FACTS[axis], text)
                self.assertIn(replacements[axis], text)
        self.assertIn(replacements["skin_tone"], text)
        self.assertIn(replacements["era"], text)
        self.assertNotIn("override conflicting", text)
        self.assertEqual(facts, FACTS)
        self.assertEqual(replacements, before)
        facts["hair"] = "changed"
        replacements["hair"] = "changed"
        self.assertEqual(r["direction_facts"], FACTS)
        self.assertEqual(r["selections"], before)
        self.assertEqual(validate_current_recipe(r), r)
        self.assertEqual(r["graph_template"]["18:17"]["inputs"]["value"], text)

    def test_articles_in_shipped_axis_values_are_not_duplicated_in_caption(self):
        for being, role in (("a woman", "a reserved dance teacher"),
                            ("an androgynous person", "an unyielding referee")):
            with self.subTest(being=being, role=role):
                r = recipe(selections={"being": being, "role": role})
                self.assertEqual(r["selections"]["being"], being)
                self.assertEqual(r["selections"]["role"], role)
                self.assertIn(f"character: {being}, {role}", r["resolved_request"])
                self.assertNotIn("adult a ", r["resolved_request"])
                self.assertNotIn("an a ", r["resolved_request"])
                self.assertNotIn("a an ", r["resolved_request"])

    def test_signature_precedes_other_physical_details(self):
        for primary in ("hair", "face", "build"):
            facts = FACTS | {"primary_axis": primary}
            text = recipe(direction_facts=facts)["resolved_request"]
            for other in {"hair", "face", "build"} - {primary}:
                self.assertLess(text.index(facts[primary]), text.index(facts[other]))
            for unwanted in ("natural adult head-to-body", "limb lengths", "override conflicting", "no text", "no watermark"):
                self.assertNotIn(unwanted, text)
            for material in ("skin", "hair", "fabric"):
                self.assertIn(material, text)
            self.assertIn("one original adult", text)

    def test_free_text_without_refinements_is_opaque_and_snapshot_is_explicit_null(self):
        direction = "A stage performer holds a brass key, with asymmetric hair and a delighted grin"
        r = recipe(direction=direction, direction_facts=None, direction_origin="user_authored")
        self.assertIsNone(r["direction_facts"])
        self.assertIn(direction, r["resolved_request"])
        self.assertIs(r["face_refine"], False)
        self.assertIs(r["upsampler"], False)
        omitted = dict(job_id="opaque", direction=direction, mode="portrait", trend_id="original",
                       selections={}, sampler_seed=0, upsampler_seed=1, upsampler=False)
        self.assertIsNone(make_recipe(**omitted)["direction_facts"])
        for selection in ({"hair": "new hair"}, {"era": "the future"}, {"being": "man"}):
            with self.subTest(selection=selection), self.assertRaisesRegex(ValueError, "edit the idea directly or choose another suggested proposal"):
                recipe(direction=direction, direction_facts=None, selections=selection)

    def test_snapshot_has_exact_keys_strict_types_and_safe_bounded_text(self):
        for malformed in ([], "facts", True, {}, FACTS | {"extra": "x"},
                          {k: v for k, v in FACTS.items() if k != "role"}):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                recipe(direction_facts=malformed)
        for axis in set(FACTS) - {"primary_axis"}:
            for value in (None, True, 2, [], {}, "", " " * 4, "x" * 301,
                          "/home/private", "http://localhost", "127.0.0.1"):
                facts = FACTS | {axis: value}
                with self.subTest(axis=axis, value=value), self.assertRaises(ValueError):
                    recipe(direction_facts=facts)
        for value in (None, [], {}, True, 1, "outfit", "Hair"):
            with self.subTest(primary=value), self.assertRaises(ValueError):
                recipe(direction_facts=FACTS | {"primary_axis": value})
        facts = FACTS | {"hair": "x" * 300}
        self.assertEqual(recipe(direction_facts=facts, direction=wording(facts))["direction_facts"], facts)

    def test_raw_wording_must_match_source_snapshot_exactly(self):
        for bad in (wording(FACTS).lower(), wording(FACTS) + " ", " " + wording(FACTS),
                    wording(FACTS).replace("an architect", "a architect"), "arbitrary authored prose"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "snapshot|facts"):
                recipe(direction=bad)
        for role in ("Engineer", "baker"):
            facts = FACTS | {"role": role}
            self.assertEqual(recipe(direction_facts=facts, direction=wording(facts))["raw_direction"], wording(facts))

    def test_v7_frozen_snapshot_and_request_cannot_be_changed(self):
        r = recipe()
        for change in ({"direction_facts": None}, {"direction_facts": FACTS | {"hair": "different"}},
                       {"resolved_request": r["resolved_request"] + " changed"}, {"schema_version": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_recipe(copy.deepcopy(r) | change)
        missing = copy.deepcopy(r)
        missing.pop("direction_facts")
        with self.assertRaises(ValueError):
            validate_recipe(missing)

    def test_modes_have_explicit_distinct_photographic_framing(self):
        portrait = recipe()["resolved_request"]
        self.assertIn("waist-up", portrait)
        self.assertIn("entire hairstyle", portrait)
        self.assertIn("face clearly visible", portrait)
        self.assertNotIn("both feet", portrait)
        full = recipe(mode="full_body")
        self.assertIn("full-length", full["resolved_request"])
        self.assertIn("both feet visible", full["resolved_request"])
        self.assertEqual(full["aspect_ratio"], "3:4 (Portrait Standard)")
        turnaround = recipe(mode="turnaround")
        self.assertEqual(turnaround["aspect_ratio"], "16:9 (Widescreen)")
        for angle in ("front view", "three-quarter view", "left profile", "back view"):
            self.assertIn(angle, turnaround["resolved_request"])
        self.assertIn("four separate photographs", turnaround["resolved_request"])

    def test_legacy_recipes_are_unchanged_and_not_replayable(self):
        import json
        from tests.character_recipe_fixtures import v6_recipe_fixture
        recipes = [v1_recipe_fixture(), v2_recipe_fixture(), v6_recipe_fixture()]
        for version in (3, 4):
            recipes.append(json.loads((ROOT / "tests/fixtures" / f"character_recipe_v{version}_frozen.json").read_text()))
        from tests.test_character_refine import V5
        recipes.append(copy.deepcopy(V5))
        for old in recipes:
            with self.subTest(version=old["schema_version"]):
                before = copy.deepcopy(old)
                self.assertEqual(validate_recipe(old), before)
                self.assertEqual(old, before)
                self.assertNotIn("waist-up", old["resolved_request"])
                self.assertNotIn("direction_facts", old)
                with self.assertRaisesRegex(ValueError, "earlier policy"):
                    validate_current_recipe(old)
                invalid_mode = copy.deepcopy(old)
                invalid_mode["mode"] = "full_body"
                with self.assertRaises(ValueError):
                    validate_recipe(invalid_mode)


if __name__ == "__main__":
    unittest.main()
