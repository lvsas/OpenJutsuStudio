"""Propagation defaults must not encode one clip's objects, lighting or camera."""
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config import RIPPLE_PROMPT

UPSTREAM_PROMPT = (
    "Use the reference video for motion, timing, camera movement, composition, "
    "and unchanged scene content, while consistently propagating the visual edit "
    "established in the first frame throughout the video."
)


class PropagationField(HTMLParser):
    def __init__(self):
        super().__init__()
        self.selected = False
        self.text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "textarea" and dict(attrs).get("name") == "propagation_prompt":
            self.selected = True

    def handle_data(self, data):
        if self.selected:
            self.text += data

    def handle_endtag(self, tag):
        if tag == "textarea":
            self.selected = False


class PromptPolicyTests(unittest.TestCase):
    def test_backend_uses_content_neutral_model_card_default(self):
        self.assertEqual(RIPPLE_PROMPT, UPSTREAM_PROMPT)

    def test_ui_and_backend_defaults_agree(self):
        parser = PropagationField()
        parser.feed((Path(__file__).resolve().parents[1] / "src/templates/index.html").read_text())
        self.assertEqual(parser.text, RIPPLE_PROMPT)
