"""The propagation instruction is a backend policy, not a public UI control."""
from pathlib import Path
import inspect
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app as app_module
import job_api
from config import RIPPLE_PROMPT
from prompt_profiles import PROMPT_PROFILES, get_prompt_profile


UPSTREAM_PROMPT = (
    "Use the reference video for motion, timing, camera movement, composition, "
    "and unchanged scene content, while consistently propagating the visual edit "
    "established in the first frame throughout the video."
)


class PromptPolicyTests(unittest.TestCase):
    def test_backend_uses_content_neutral_model_card_default(self):
        self.assertEqual(RIPPLE_PROMPT, UPSTREAM_PROMPT)

    def test_propagation_prompt_is_not_a_public_job_parameter(self):
        self.assertNotIn("propagation_prompt", inspect.signature(app_module.create_job).parameters)
        template = (Path(__file__).resolve().parents[1] / "src/templates/index.html").read_text()
        self.assertNotIn('name="propagation_prompt"', template)

    def test_ltx_prompt_profile_is_explicit_and_the_only_enabled_profile(self):
        self.assertEqual(set(PROMPT_PROFILES), {"ltx25-ripple"})
        self.assertEqual(get_prompt_profile("ltx25-ripple").propagation_prompt, RIPPLE_PROMPT)
        self.assertEqual(
            get_prompt_profile("ltx25-ripple").compose_frame_edit(
                "Recast the singer", "", ["the singer on the right"]),
            "Reference 1 applies to: the singer on the right. Requested edit: Recast the singer",
        )

    def test_job_submission_uses_the_backend_propagation_policy(self):
        profile = get_prompt_profile("ltx25-ripple")
        recipe = job_api._build_recipe(
            "Recast the singer", "", [], profile, "compiled edit", 19, 1.2,
            {"frames": 9, "fps": 24.0}, 704, 384,
        )
        options = job_api._pipeline_options(recipe, [])
        self.assertEqual(recipe["propagation_prompt"], RIPPLE_PROMPT)
        self.assertEqual(options["ripple_prompt"], RIPPLE_PROMPT)
