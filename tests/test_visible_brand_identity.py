"""Visible product identity: Open Jutsu Studio in pages, captions and public docs.

Technical contracts deliberately keep their historical identifiers — node classes,
capsule formats, browser keys, output prefixes, HTTP headers, package paths and
remotes are not brand strings. This module locks both sides of that line so a
future "rename" cannot silently break operations.
"""
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "src/templates"
NAME = "Open Jutsu Studio"
PAGES = ("index", "character", "h3", "timeline", "settings", "assembly")
CAPTION_SOURCES = (
    "src/static/app.js",
    "src/static/h3-take.js",
    "src/static/share-reel.js",
    "src/static/timeline-export-ui.js",
)


def text_of(markup):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", markup)).strip()


def read(name):
    return (ROOT / name).read_text()


class TemplateIdentity(unittest.TestCase):
    def test_every_page_title_names_the_studio(self):
        for page in PAGES:
            with self.subTest(page=page):
                title = re.search(r"<title>(.*?)</title>", (TEMPLATES / f"{page}.html").read_text(), re.S).group(1).strip()
                self.assertIn(NAME, title)
                self.assertNotIn("OpenGenjutsu", title)

    def test_wordmark_keeps_its_markup_and_reads_open_jutsu_studio(self):
        for page in PAGES:
            with self.subTest(page=page):
                source = (TEMPLATES / f"{page}.html").read_text()
                anchor = re.search(r'<a class="wordmark"[^>]*>', source).group(0)
                self.assertIn(f'aria-label="{NAME} home"', anchor)
                body = re.search(r'<a class="wordmark"[^>]*>(.*?)</a>', source, re.S).group(1)
                self.assertIn("OPEN<span>JUTSU</span>", body)
                self.assertNotIn("GENJUTSU", body)
                self.assertEqual(text_of(body), "OPENJUTSU STUDIO")

    def test_studio_suffix_stays_text_coloured(self):
        css = read("src/static/app.css")
        self.assertIn(".wordmark span { color: var(--accent); }", css)
        rule = re.search(r"\.wordmark \.wordmark-studio \{([^}]*)\}", css)
        self.assertIsNotNone(rule, "The STUDIO suffix needs its own wordmark rule")
        self.assertIn("color: var(--text)", rule.group(1))


class CaptionIdentity(unittest.TestCase):
    def test_captions_credit_the_studio_and_its_hashtag(self):
        for name in CAPTION_SOURCES:
            with self.subTest(source=name):
                source = read(name)
                self.assertRegex(source, r"Made with Open Jutsu Studio\.")
                self.assertRegex(source, r"#OpenJutsuStudio")

    def test_no_visible_caption_still_prints_the_old_product_word(self):
        for name in CAPTION_SOURCES:
            with self.subTest(source=name):
                self.assertNotRegex(read(name), r"OpenGenjutsu(?![A-Za-z])")
        self.assertRegex(read("src/static/share-reel.js"), r"My Open Jutsu Studio Swap")
        self.assertRegex(read("src/static/share-reel.js"),
                         r"Same performance\. A new identity\. Made with Open Jutsu Studio\.")

    def test_share_dialog_eyebrow_words_the_product_in_two_tone_letters(self):
        """The dialog is user-visible markup, so it cannot keep the retired word."""
        source = read("src/static/share-reel.js")
        eyebrow_match = re.search(r'<p class="eyebrow">(.*?)</p>', source, re.S)
        assert eyebrow_match is not None
        eyebrow = eyebrow_match.group(1)
        self.assertNotIn("GENJUTSU", eyebrow)
        self.assertEqual(re.sub(r"\s+", " ", text_of(eyebrow)), "OPENJUTSU STUDIO / CHARACTER SWAP")


class ServedMetadata(unittest.TestCase):
    def test_openapi_title_names_the_studio(self):
        sys.path.insert(0, str(ROOT / "src"))
        from app import app
        self.assertEqual(app.title, NAME)


class PublicDocs(unittest.TestCase):
    def test_public_headings_name_the_studio(self):
        expected = {
            "README.md": f"# {NAME}",
            "ROADMAP.md": f"# {NAME} Roadmap",
            "CONTRIBUTING.md": f"# Contributing to {NAME}",
        }
        for name, heading in expected.items():
            with self.subTest(document=name):
                first = read(name).splitlines()[0]
                self.assertEqual(first, heading)
                self.assertNotIn("OpenGenjutsu", read(name))

    def test_public_prose_names_the_studio(self):
        self.assertRegex(read("README.md"), r"Open Jutsu Studio connects native-file publication")
        self.assertRegex(read("README.md"), r"\*\*Open Jutsu Studio\*\* — the connected studio")
        self.assertRegex(read("docs/model-licences.md"), r"Open Jutsu Studio's application code")


class TechnicalContracts(unittest.TestCase):
    """Brand editing must not reach these strings."""

    CASES = (
        ("src/static/studio-utils.js", "window.OpenGenjutsuStudio = {"),
        ("src/static/project-session.js", "'opengenjutsu.workspace.project'"),
        ("src/static/sequence-workspace.js", "'opengenjutsu.sequence.project'"),
        ("src/static/continuity-attempt-client.js", "'opengenjutsu.sequence.pending-generation'"),
        ("src/static/app.js", "'opengenjutsu:take-ready'"),
        ("src/continuable_take.py", "'opengenjutsu-continuable-take'"),
        ("src/h3_continuity_graphs.py", "'OpenGenjutsuH3PublishClip'"),
        ("src/h3_continuity_graphs.py", "'OpenGenjutsu/continuity/takes/'"),
        ("src/h3_family_graphs.py", "'OpenGenjutsuH3RestageFamily'"),
        ("src/continuable_take_api.py", "'X-OpenGenjutsu-Integrity'"),
    )

    def test_identifiers_keep_their_historical_names(self):
        for name, marker in self.CASES:
            with self.subTest(source=name, marker=marker):
                self.assertIn(marker, read(name))

    def test_node_pack_and_template_paths_are_untouched(self):
        self.assertTrue((ROOT / "custom_nodes/opengenjutsu_continuity/__init__.py").is_file())
        self.assertEqual(
            sorted(path.name for path in TEMPLATES.glob("*.html")),
            ["assembly.html", "character.html", "export-dialog.html", "h3.html", "index.html",
             "settings.html", "timeline.html"],
        )


if __name__ == "__main__":
    unittest.main()
