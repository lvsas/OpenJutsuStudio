"""Reference-first submission contract; inference is mocked, not quality evidence."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app as app_module
import core
import job_api
from fastapi.testclient import TestClient
from prompt_profiles import PROMPT_POLICY_VERSION, get_prompt_profile
from tests.test_app import _ImmediateExecutor


class OptionalPromptTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.observed = {}

        async def save_video(upload, destination, _limit):
            destination.write_bytes(await upload.read())
            return {"width": 1280, "height": 704, "fps": 24.0, "frames": 9, "duration": 9/24}

        def runner(job, video, opts):
            self.observed.update(job=job, video=video, opts=opts)

        patches = [
            patch.object(core, "WORK", root),
            patch.object(app_module, "MEDIA_DIR", root / "media"),
            patch.object(app_module, "check_readiness", return_value={"ready": True}),
            patch.object(app_module, "_EXECUTOR", _ImmediateExecutor()),
            patch.object(app_module, "PIPELINE_RUNNER", runner),
            patch.object(job_api, "save_video", save_video),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(app_module.app)

    def submit(self, count=1, **data):
        files = [("video", ("source.mp4", b"source", "video/mp4"))]
        files.extend(("reference_images", (f"ref{i}.png", b"ref", "image/png"))
                     for i in range(count))
        return self.client.post("/api/jobs", files=files, data=data)

    def test_missing_prompt_with_reference_builds_and_records_internal_instruction(self):
        response = self.submit()
        self.assertEqual(response.status_code, 202, response.text)
        job = core.Job.load(response.json()["job_id"])
        recipe = job.meta["take_recipe"]
        self.assertEqual(recipe["edit_brief"], "")
        self.assertEqual(recipe["prompt_policy_version"], PROMPT_POLICY_VERSION)
        self.assertIn("Replace the main person", job.prompt)
        self.assertEqual(recipe["effective_edit_prompt"], job.prompt)
        self.assertEqual(recipe["propagation_prompt"], self.observed["opts"]["ripple_prompt"])

    def test_empty_and_whitespace_prompt_with_reference_are_accepted(self):
        for text in ("", "  \n "):
            with self.subTest(text=text):
                response = self.submit(edit_prompt=text)
                self.assertEqual(response.status_code, 202, response.text)

    def test_two_references_without_prompt_or_mapping_are_accepted(self):
        response = self.submit(count=2)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertIn("two main people", self.observed["job"].prompt)
        self.assertNotIn("on the left", self.observed["job"].prompt)
        self.assertEqual(len(self.observed["opts"]["reference_images"]), 2)

    def test_optional_short_direction_is_preserved_as_extra_instruction(self):
        response = self.submit(edit_prompt="red scarf")
        self.assertEqual(response.status_code, 202, response.text)
        self.assertIn("takes precedence over the default recast): red scarf", self.observed["job"].prompt)
        self.assertEqual(self.observed["job"].meta["take_recipe"]["edit_brief"], "red scarf")

    def test_no_reference_and_no_direction_rejects_before_dispatch(self):
        for text in ("", "  "):
            with self.subTest(text=text):
                response = self.submit(count=0, edit_prompt=text)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertFalse(self.observed)

    def test_text_only_edit_keeps_existing_prompt_contract(self):
        response = self.submit(count=0, edit_prompt="Change the jacket")
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.observed["job"].prompt, "Change the jacket")

    def test_reference_only_replay_keeps_recorded_prompt_without_recompiling(self):
        response = self.submit()
        parent = core.Job.load(response.json()["job_id"])
        result = core.WORK / "media" / "result.mp4"
        result.write_bytes(b"finished")
        parent.status, parent.result = "done", str(result)
        parent.meta["shots"] = [{"start": 0, "end": 8}]
        from take_capsule_api import freeze_take_capsule
        freeze_take_capsule(parent, result)
        parent.save()
        with patch("prompt_profiles.PromptProfile.compose_frame_edit", side_effect=AssertionError("recompiled replay")):
            replay = self.client.post(f"/api/jobs/{parent.id}/replay")
        self.assertEqual(replay.status_code, 202, replay.text)
        child = core.Job.load(replay.json()["job_id"])
        self.assertEqual(child.prompt, parent.prompt)
        self.assertEqual(child.meta["take_recipe"]["edit_brief"], "")
        self.assertEqual(child.meta["take_recipe"]["prompt_policy_version"], PROMPT_POLICY_VERSION)

    def test_reference_hints_remain_optional_and_are_not_fabricated(self):
        profile = get_prompt_profile("ltx25-ripple")
        prompt = profile.compose_frame_edit("", "", ["the singer on the right"], reference_count=1)
        self.assertIn("Reference 1 applies to: the singer on the right.", prompt)
        self.assertNotIn("Reference 2", prompt)


if __name__ == "__main__":
    unittest.main()
