"""Integrity/read-versus-replay contract for Character Capsules."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tests.character_recipe_fixtures import v1_recipe_fixture  # noqa: E402
from core import Job  # noqa: E402
from character_capsule import freeze_capsule, get_capsule, replay_recipe  # noqa: E402
from character_recipe import ENGINE, digest_json, make_recipe  # noqa: E402


class CharacterCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.media = Path(self.tmp.name) / "media"
        self.media.mkdir()
        self.image = self.media / "character.png"
        self.caption = self.media / "caption.txt"
        self.image.write_bytes(b"verified-image-bytes")
        self.caption.write_text("Studio photograph of an original person.", encoding="utf-8")
        self.recipe = make_recipe(
            job_id="character_capsule_1", direction="an original locksmith", mode="portrait",
            trend_id="original", selections={"hair": "flat top"}, sampler_seed=42,
            upsampler_seed=42, upsampler=True)
        self.job = Job(id="character_capsule_1", engine=ENGINE, status="done", result=str(self.image),
                       meta={"character_caption": str(self.caption)})

    def test_freeze_and_read_preserve_recipe_artifacts_and_replay_contract(self):
        frozen = freeze_capsule(self.job, self.recipe, self.image, self.caption, self.media)
        self.assertEqual(frozen["job_id"], self.job.id)
        self.assertEqual(frozen["engine"], ENGINE)
        self.assertEqual(frozen["recipe"], self.recipe)
        self.assertRegex(frozen["capsule_id"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(frozen["assets"]["image"]["size_bytes"], self.image.stat().st_size)
        self.assertEqual(frozen["assets"]["caption"]["size_bytes"], self.caption.stat().st_size)
        self.assertIn("pixel-identical", frozen["replay"]["contract"])
        self.assertEqual(frozen["resolved_caption"], "Studio photograph of an original person.")
        self.assertEqual(get_capsule(self.job), frozen)
        self.assertEqual(replay_recipe(self.job, self.media), self.recipe)

    def test_freeze_can_run_while_the_job_is_still_running(self):
        self.job.status = "running"
        frozen = freeze_capsule(self.job, self.recipe, self.image, self.caption, self.media)
        self.assertEqual(frozen["job_id"], self.job.id)
        with self.assertRaises(ValueError):
            get_capsule(self.job)

    def test_empty_image_cannot_be_frozen(self):
        self.image.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "image"):
            freeze_capsule(self.job, self.recipe, self.image, self.caption, self.media)

    def test_empty_or_non_utf8_caption_cannot_be_frozen(self):
        self.caption.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "caption"):
            freeze_capsule(self.job, self.recipe, self.image, self.caption, self.media)
        self.caption.write_bytes(b"\xff")
        with self.assertRaisesRegex(ValueError, "caption"):
            freeze_capsule(self.job, self.recipe, self.image, self.caption, self.media)

    def test_recipe_cannot_be_frozen_on_a_different_job(self):
        wrong_job = Job(id="different_job", engine=ENGINE, status="done", result=str(self.image))
        with self.assertRaisesRegex(ValueError, "recipe does not belong"):
            freeze_capsule(wrong_job, self.recipe, self.image, self.caption, self.media)

    def test_caption_cannot_be_frozen_from_another_job(self):
        other_caption = self.media / "other-job.txt"
        other_caption.write_text("other caption", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "caption does not match"):
            freeze_capsule(self.job, self.recipe, self.image, other_caption, self.media)
        self.assertEqual(self.job.meta["character_caption"], str(self.caption))

    def test_tampering_blocks_read_and_artifact_mutation_blocks_replay(self):
        freeze_capsule(self.job, self.recipe, self.image, self.caption, self.media)
        tampered = copy.deepcopy(self.job.meta["character_capsule"])
        tampered["recipe"]["raw_direction"] = "changed"
        self.job.meta["character_capsule"] = tampered
        with self.assertRaisesRegex(ValueError, "changed"):
            get_capsule(self.job)

        freeze_capsule(self.job, self.recipe, self.image, self.caption, self.media)
        self.caption.write_text("changed caption", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "input changed"):
            replay_recipe(self.job, self.media)

    def test_rehashed_malformed_artifact_metadata_is_not_historical_evidence(self):
        frozen = freeze_capsule(self.job, self.recipe, self.image, self.caption, self.media)
        malformed = copy.deepcopy(frozen)
        malformed["assets"] = {"image": None, "caption": None}
        malformed.pop("capsule_id")
        malformed["capsule_id"] = "sha256:" + digest_json(malformed)
        self.job.meta["character_capsule"] = malformed
        with self.assertRaisesRegex(ValueError, "artifact"):
            get_capsule(self.job)

    def test_v1_capsule_evidence_remains_readable_but_cannot_replay_under_v2_policy(self):
        legacy = v1_recipe_fixture()
        legacy_job = Job(id=legacy["job_id"], engine=ENGINE, status="done", result=str(self.image),
                         meta={"character_caption": str(self.caption)})
        frozen = freeze_capsule(legacy_job, legacy, self.image, self.caption, self.media)
        self.assertEqual(frozen["recipe"]["schema_version"], 1)
        self.assertEqual(get_capsule(legacy_job)["recipe"], legacy)
        with self.assertRaisesRegex(ValueError, "earlier policy"):
            replay_recipe(legacy_job, self.media)

    def test_historical_capsule_is_readable_but_current_policy_is_checked_only_on_replay(self):
        frozen = freeze_capsule(self.job, self.recipe, self.image, self.caption, self.media)
        historical = copy.deepcopy(frozen)
        historical.pop("resolved_caption")
        historical["schema_version"] = 1
        without_id = copy.deepcopy(historical)
        without_id.pop("capsule_id")
        historical["capsule_id"] = "sha256:" + digest_json(without_id)
        self.job.meta["character_capsule"] = historical
        self.assertEqual(get_capsule(self.job)["schema_version"], 1)
        broken_recipe = copy.deepcopy(historical["recipe"])
        broken_recipe["prompt_policy"] = "obsolete"
        historical["recipe"] = broken_recipe
        historical["recipe_sha256"] = digest_json(broken_recipe)
        without_id = copy.deepcopy(historical)
        without_id.pop("capsule_id")
        historical["capsule_id"] = "sha256:" + digest_json(without_id)
        self.job.meta["character_capsule"] = historical
        self.assertEqual(get_capsule(self.job)["recipe"]["prompt_policy"], "obsolete")
        with self.assertRaises(ValueError):
            replay_recipe(self.job, self.media)


if __name__ == "__main__":
    unittest.main()
