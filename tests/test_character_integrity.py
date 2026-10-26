"""Read-only capsule evidence must enforce types and supplied graph integrity."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tests import test_character_capsule as capsule_tests
from tests.character_recipe_fixtures import v1_recipe_fixture, v2_recipe_fixture, v6_recipe_fixture
from character_capsule import freeze_capsule, get_capsule
from character_recipe import digest_json, make_recipe, validate_recipe


def seal(capsule):
    """Recompute only the outer integrity layers, not the declared graph digest."""
    capsule["recipe_sha256"] = digest_json(capsule["recipe"])
    capsule.pop("capsule_id", None)
    capsule["capsule_id"] = "sha256:" + digest_json(capsule)
    return capsule


class RecipeIntegrityTests(unittest.TestCase):
    def test_historical_recipe_versions_are_exact_integers_before_dispatch(self):
        for fixture in (v1_recipe_fixture, v2_recipe_fixture, v6_recipe_fixture):
            valid = fixture()
            aliases = [float(valid["schema_version"])]
            if valid["schema_version"] == 1:
                aliases.append(True)
            for alias in aliases:
                with self.subTest(version=alias, kind=type(alias).__name__):
                    with self.assertRaises(ValueError):
                        validate_recipe(valid | {"schema_version": alias})

    def test_supplied_graph_hash_must_match_declared_and_expected_hashes(self):
        current = make_recipe(job_id="graph_false_zero", direction="An original adult locksmith",
                              mode="portrait", trend_id="original", selections={}, sampler_seed=1,
                              upsampler_seed=2, upsampler=False)
        for valid in (v6_recipe_fixture(), current):
            for value in (int(valid["upsampler"]), float(valid["upsampler"])):
                for rehash_graph in (False, True):
                    broken = copy.deepcopy(valid)
                    broken["graph_template"]["18:16"]["inputs"]["switch"] = value
                    if rehash_graph:
                        broken["graph_sha256"] = digest_json(broken["graph_template"])
                    with self.subTest(version=valid["schema_version"], value=value,
                                      rehash_graph=rehash_graph):
                        with self.assertRaisesRegex(ValueError, "graph"):
                            validate_recipe(broken)


class CapsuleIntegrityTests(unittest.TestCase):
    setUp = capsule_tests.CharacterCapsuleTests.setUp

    def frozen(self, recipe=None, envelope=None):
        recipe = self.recipe if recipe is None else recipe
        self.job.id = recipe["job_id"]
        frozen = freeze_capsule(self.job, recipe, self.image, self.caption, self.media)
        if envelope is not None:
            frozen["schema_version"] = envelope
            if envelope == 1:
                frozen.pop("resolved_caption", None)
        return seal(frozen)

    def reject(self, capsule):
        self.job.meta["character_capsule"] = seal(capsule)
        with self.assertRaises(ValueError):
            get_capsule(self.job)

    def test_unknown_recipe8_cannot_hide_in_legacy_capsule(self):
        for envelope in (1, 2):
            broken = self.frozen(v2_recipe_fixture(), envelope)
            broken["recipe"]["schema_version"] = 8
            broken["recipe"]["prompt_policy"] = "character-v8"
            with self.subTest(envelope=envelope):
                self.reject(broken)

    def test_modern_recipe_cannot_hide_in_legacy_capsule(self):
        for envelope in (1, 2):
            for recipe in (v6_recipe_fixture(), self.recipe):
                with self.subTest(envelope=envelope, recipe=recipe["schema_version"]):
                    self.reject(self.frozen(recipe, envelope))

    def test_envelope_versions_are_exact_integers(self):
        for recipe, envelope, aliases in (
            (v1_recipe_fixture(), 1, (True, 1.0)),
            (v2_recipe_fixture(), 2, (2.0,)),
            (v6_recipe_fixture(), 6, (6.0,)),
            (self.recipe, 7, (7.0,)),
        ):
            for alias in aliases:
                broken = self.frozen(recipe, envelope)
                broken["schema_version"] = alias
                with self.subTest(envelope=alias, kind=type(alias).__name__):
                    self.reject(broken)

    def test_legacy_inner_recipe_versions_are_exact_integers(self):
        for envelope in (1, 2):
            for alias in (True, 1.0):
                broken = self.frozen(v1_recipe_fixture(), envelope)
                broken["recipe"]["schema_version"] = alias
                with self.subTest(envelope=envelope, recipe=alias, kind=type(alias).__name__):
                    self.reject(broken)

    def test_v6_and_v7_require_matching_recipe_versions_and_boolean_refine(self):
        for recipe in (v6_recipe_fixture(), self.recipe):
            for version in (float(recipe["schema_version"]), 8):
                broken = self.frozen(recipe)
                broken["recipe"]["schema_version"] = version
                with self.subTest(envelope=recipe["schema_version"], recipe=version):
                    self.reject(broken)
            for value in (0, 1, None):
                broken = self.frozen(recipe)
                broken["recipe"]["face_refine"] = value
                with self.subTest(version=recipe["schema_version"], refine=value):
                    self.reject(broken)

    def test_v7_snapshot_shape_canonical_values_and_source_are_checked_on_read(self):
        facts = self.recipe["direction_facts"]
        for malformed in ({}, [], True, facts | {"extra": "x"},
                          facts | {"hair": " leading space"},
                          facts | {"hair": "http://localhost"},
                          facts | {"primary_axis": "outfit"},
                          facts | {"hair": "a different hairstyle"}):
            broken = self.frozen()
            broken["recipe"]["direction_facts"] = malformed
            with self.subTest(facts=malformed):
                self.reject(broken)
        broken = self.frozen()
        broken["recipe"].pop("direction_facts")
        self.reject(broken)

    def test_supplied_graph_digest_is_verified_even_with_rehashed_capsule(self):
        for recipe in (v1_recipe_fixture(), v6_recipe_fixture(), self.recipe):
            broken = self.frozen(recipe)
            graph = broken["recipe"]["graph_template"]
            graph["18:16"]["inputs"]["switch"] = int(recipe["upsampler"])
            with self.subTest(version=recipe["schema_version"]):
                self.reject(broken)

    def test_rehashed_graph_cannot_replace_boolean_switch_with_integer(self):
        for recipe in (v1_recipe_fixture(), v6_recipe_fixture(), self.recipe):
            broken = self.frozen(recipe)
            graph = broken["recipe"]["graph_template"]
            graph["18:16"]["inputs"]["switch"] = int(recipe["upsampler"])
            broken["recipe"]["graph_sha256"] = digest_json(graph)
            with self.subTest(version=recipe["schema_version"]):
                self.reject(broken)

    def test_frozen_recipe_structure_and_replay_boolean_cannot_be_rehashed_away(self):
        for mutate in (
            lambda c: c["recipe"].pop("graph_template"),
            lambda c: c["recipe"].update(engine="another-engine"),
            lambda c: c["recipe"].update(upsampler=1),
            lambda c: c["replay"].update(model_weights_hashed=0),
        ):
            broken = self.frozen()
            mutate(broken)
            with self.subTest(mutation=mutate):
                self.reject(broken)

    def test_historical_read_does_not_rebuild_or_apply_current_policy_or_weights(self):
        frozen = self.frozen(v2_recipe_fixture())
        frozen["recipe"]["prompt_policy"] = "obsolete"
        self.job.meta["character_capsule"] = seal(frozen)
        before = copy.deepcopy(self.job.meta)
        with patch("character_capsule.validate_current_recipe", side_effect=AssertionError("replay only")), \
                patch("character_capsule.validate_recipe", side_effect=AssertionError("creation only")), \
                patch("character_recipe.build_character_graph", side_effect=AssertionError("no rebuild")), \
                patch("character_recipe.MODEL_ROLES", {"unet": "different-current-model"}):
            self.assertEqual(get_capsule(self.job), frozen)
        self.assertEqual(self.job.meta, before)

    def test_valid_v7_null_snapshot_remains_readable_without_rebuilding(self):
        opaque = make_recipe(job_id=self.job.id, direction="An original adult locksmith", mode="portrait",
                             trend_id="original", selections={}, sampler_seed=1, upsampler_seed=2,
                             upsampler=False, direction_origin="user_authored")
        for valid in (opaque, self.recipe):
            frozen = self.frozen(valid)
            with self.subTest(snapshot=valid["direction_facts"]), \
                    patch("character_recipe._request_v7", side_effect=AssertionError("no policy rebuild")):
                self.assertEqual(get_capsule(self.job), frozen)


if __name__ == "__main__":
    unittest.main()
