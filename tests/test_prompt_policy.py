"""The propagation instruction is a backend policy, not a public UI control."""
from pathlib import Path
import inspect
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app as app_module
from config import RIPPLE_PROMPT


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

    def test_job_submission_uses_the_backend_propagation_policy(self):
        source = Path(app_module.__file__).read_text()
        self.assertIn('"ripple_prompt": core.RIPPLE_PROMPT', source)
