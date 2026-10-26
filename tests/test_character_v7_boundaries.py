"""Exercise V7 through real ASGI queue/replay and mocked artifact collection."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tests import test_character_api as api_tests
from tests import test_character_pipeline as worker_tests
from tests.test_character_direction_v7 import FACTS, wording, recipe
from tests.character_recipe_fixtures import v6_recipe_fixture
from character_capsule import freeze_capsule, get_capsule, replay_recipe
from character_pipeline import run_character_pipeline, _validate_png
from character_recipe import digest_json
import core


class V7APIBoundaryTests(unittest.TestCase):
    setUp = api_tests.CharacterAPITests.setUp

    def post(self, **changes):
        payload = dict(direction=wording(FACTS), direction_facts=copy.deepcopy(FACTS),
                       selections={"hair": "a giant black geometric pompadour"})
        return self.client.post("/api/characters/jobs", json=payload | changes)

    def test_api_replaces_the_old_hair_not_merely_appends_an_override(self):
        response = self.post()
        self.assertEqual(response.status_code, 202, response.text)
        r = self.dispatch.call_args.args[1]["recipe"]
        self.assertNotIn(FACTS["hair"], r["resolved_request"])
        self.assertIn("a giant black geometric pompadour", r["resolved_request"])

    def test_snapshot_is_frozen_and_replayed_without_changing_parent(self):
        response = self.post(mode="full_body")
        self.assertEqual(response.status_code, 202, response.text)
        job, opts = self.dispatch.call_args.args
        r = opts["recipe"]
        self.assertEqual(r["schema_version"], 7)
        self.assertEqual(r["direction_facts"], FACTS)
        self.assertEqual(r["raw_direction"], wording(FACTS))
        self.assertNotIn(FACTS["hair"], r["resolved_request"])
        self.assertIn("a giant black geometric pompadour", r["resolved_request"])
        self.assertIs(r["upsampler"], False)
        self.assertIs(r["face_refine"], False)
        self.assertEqual(core.Job.load(job.id).meta["character_recipe"], r)
        image, caption = self.media / "image.png", self.media / "caption.txt"
        image.write_bytes(api_tests.png()); caption.write_text(r["resolved_request"])
        job.result, job.status = str(image), "done"
        job.meta["character_caption"] = str(caption)
        frozen = freeze_capsule(job, r, image, caption, self.media)
        self.assertEqual(frozen["schema_version"], 7)
        job.save()
        parent_bytes = job.path.read_bytes()
        self.assertEqual(self.client.get(f"/api/characters/jobs/{job.id}/capsule").json(), frozen)
        replay = self.client.post(f"/api/characters/jobs/{job.id}/replay")
        self.assertEqual(replay.status_code, 202, replay.text)
        child, child_opts = self.dispatch.call_args.args
        for key in ("raw_direction", "direction_facts", "selections", "mode", "resolved_request", "upsampler", "face_refine"):
            self.assertEqual(child_opts["recipe"][key], r[key])
        self.assertEqual(core.Job.load(child.id).meta["character_recipe"], child_opts["recipe"])
        self.assertEqual(job.path.read_bytes(), parent_bytes)

    def test_opaque_refinements_and_invalid_snapshots_fail_before_readiness(self):
        self.ready.return_value = {"ready": False, "issues": ["offline"]}
        for changes in ({"direction_facts": None}, {"direction_facts": {}},
                        {"direction": "freely edited idea"}, {"direction_facts": FACTS | {"hair": 1}}):
            response = self.post(**changes)
            self.assertEqual(response.status_code, 422, response.text)
        blocked = self.post(direction_facts=None)
        self.assertIn("edit the idea directly or choose another suggested proposal", blocked.text)
        self.ready.assert_not_called()
        self.dispatch.assert_not_called()
        self.assertEqual(core.Job.all(), [])

    def test_legacy_v6_capsule_is_readable_but_replay_cannot_upgrade_it(self):
        old = v6_recipe_fixture()
        # Public routes only accept production UUIDs; preserve the captured request while rebinding
        # this isolated evidence to a valid test job namespace, never via the current assembler.
        from character_graphs import build_character_graph
        old["job_id"] = "6" * 32
        old["graph_template"] = build_character_graph(old["resolved_request"], 11, old["aspect_ratio"],
                                                      True, old["job_id"], upsampler_seed=29)
        old["graph_sha256"] = digest_json(old["graph_template"])
        image, caption = self.media / "old.png", self.media / "old.txt"
        image.write_bytes(api_tests.png()); caption.write_text("Historical caption")
        job = core.Job(id=old["job_id"], engine=old["engine"], status="done", result=str(image),
                       meta={"character_caption": str(caption), "character_recipe": old})
        frozen = freeze_capsule(job, old, image, caption, self.media)
        self.assertEqual(frozen["schema_version"], 6)
        job.save(); before = job.path.read_bytes()
        read = self.client.get(f"/api/characters/jobs/{job.id}/capsule")
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json(), frozen)
        refused = self.client.post(f"/api/characters/jobs/{job.id}/replay")
        self.assertEqual(refused.status_code, 409)
        self.assertIn("earlier policy", refused.text)
        self.dispatch.assert_not_called()
        self.assertEqual(job.path.read_bytes(), before)


class V7WorkerBoundaryTests(unittest.TestCase):
    setUp = worker_tests.CharacterPipelineTests.setUp
    _artifacts = worker_tests.CharacterPipelineTests._artifacts

    def test_legacy_refined_v6_preserves_base_and_cannot_upgrade_on_replay(self):
        from character_refine import append_face_refine, REFINE_MODEL_ROLES
        old = v6_recipe_fixture()
        old["face_refine"] = True
        old["model_roles"].update(REFINE_MODEL_ROLES)
        old["graph_template"] = append_face_refine(old["graph_template"], seed=11, job_id=old["job_id"])
        old["graph_sha256"] = digest_json(old["graph_template"])
        artifacts = self._artifacts(self.media)
        base = self.media / "legacy_base.png"
        base.write_bytes(worker_tests.png())
        job = core.Job(id=old["job_id"], engine=old["engine"], status="done", result=str(artifacts["image"]),
                       meta={"character_caption": str(artifacts["caption"]), "character_base_image": str(base)})
        frozen = freeze_capsule(job, old, artifacts["image"], artifacts["caption"], self.media)
        self.assertEqual(frozen["schema_version"], 6)
        self.assertEqual(frozen["recipe"], old)
        self.assertEqual(set(frozen["assets"]), {"image", "caption", "base_image"})
        self.assertEqual(get_capsule(job), frozen)
        with self.assertRaisesRegex(ValueError, "earlier policy"):
            replay_recipe(job, self.media)
        self.assertTrue(base.is_file())

    def test_full_body_rejects_a_widescreen_png(self):
        artifacts = self._artifacts(self.media, image_bytes=worker_tests.png(1600, 900))
        with self.assertRaisesRegex(ValueError, "aspect ratio"):
            _validate_png(artifacts["image"], "full_body")

    def test_full_body_png_capsule_and_refine_preserve_base(self):
        self.recipe = recipe(job_id=self.job.id, mode="full_body", face_refine=True)
        self.job.meta["character_recipe"] = self.recipe
        def artifacts(c, g, requests, folder, on_progress):
            result = self._artifacts(folder)
            result["base_image"] = folder / "base.png"
            result["base_image"].write_bytes(worker_tests.png())
            return result
        with patch("character_pipeline.make_client", return_value=MagicMock()), patch("character_pipeline._run_graph_artifacts", side_effect=artifacts):
            run_character_pipeline(self.job, {"recipe": self.recipe, "media_dir": self.media})
        self.assertEqual(self.job.status, "done", self.job.error)
        self.assertEqual(_validate_png(Path(self.job.result), "full_body"), (880, 1184))
        frozen = get_capsule(self.job)
        self.assertEqual(frozen["schema_version"], 7)
        self.assertEqual(set(frozen["assets"]), {"image", "caption", "base_image"})
        self.assertEqual(replay_recipe(self.job, self.media), self.recipe)
        self.assertEqual(frozen["recipe"]["graph_template"]["18:7"]["inputs"]["steps"], 50)
        self.assertEqual(frozen["recipe"]["graph_template"]["18:7"]["inputs"]["cfg"], 3.5)
        for changed_version in (6, 2):
            broken = copy.deepcopy(frozen)
            broken["schema_version"] = changed_version
            broken.pop("capsule_id")
            broken["capsule_id"] = "sha256:" + digest_json(broken)
            self.job.meta["character_capsule"] = broken
            with self.assertRaises(ValueError):
                get_capsule(self.job)


if __name__ == "__main__":
    unittest.main()
