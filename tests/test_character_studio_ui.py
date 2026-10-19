"""Character stage interface contracts: navigation order, payload shape, no locks, no ETA."""
import os
import re
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
import character_studio_app  # noqa: E402

NAV_BLOCK = re.compile(r"<(?:nav|div)[^>]*class=\"engine-switch\".*?</(?:nav|div)>", re.S)


def nav_of(markup: str) -> str:
    """The stage switcher only: the wordmark also links to '/', which is not navigation order."""
    match = NAV_BLOCK.search(markup)
    assert match, "every page must expose the stage switcher"
    return match.group(0)


class CharacterStudioUITests(unittest.TestCase):
    def setUp(self):
        self.page = (SRC / "templates" / "character.html").read_text()
        self.js = (SRC / "static" / "character.js").read_text()
        self.css = (SRC / "static" / "character.css").read_text()
        self.index = (SRC / "templates" / "index.html").read_text()
        self.h3 = (SRC / "templates" / "h3.html").read_text()

    def test_characters_is_the_leftmost_stage_on_every_page(self):
        for name, markup in (("character.html", self.page), ("index.html", self.index), ("h3.html", self.h3)):
            with self.subTest(page=name):
                nav = nav_of(markup)
                order = [nav.index(f'href="{href}"') for href in ("/characters", "/", "/h3")]
                self.assertEqual(order, sorted(order), f"{name} must list Characters before the studios")

    def test_page_loads_the_studio_shell_and_its_own_assets(self):
        self.assertIn("/static/app.css", self.page)
        self.assertIn("/static/character.css", self.page)
        self.assertIn("/static/character.js", self.page)
        self.assertIn('data-engine="characters"', self.page)
        self.assertIn("Viral", self.page)
        self.assertNotIn("<style>", self.page, "the page must use the shared stylesheet, not inline CSS")
        self.assertNotIn("style=", self.page)

    def test_optional_axes_are_editable_fields_not_a_lock_toggle(self):
        self.assertNotIn("🔒", self.page + self.js)
        self.assertNotIn("padlock", (self.page + self.js).lower())
        self.assertNotRegex(self.css, r"aria-pressed|\.locked|\.is-locked")
        for axis in ("being", "build", "skin_tone", "hair", "face", "outfit", "role", "era",
                     "accessory", "absurdity"):
            self.assertIn(f'"{axis}"', self.js, f"{axis} must be part of the optional control vocabulary")
        self.assertIn('input.placeholder = "model decides"', self.js)
        self.assertIn('input.type = "text"', self.js)

    def test_payload_reaches_the_api_with_the_expected_contract(self):
        for key in ("direction", "mode", "trend_id", "selections", "sampler_seed", "upsampler_seed",
                    "upsampler"):
            self.assertIn(key, self.js, f"the request must send {key}")
        self.assertIn('fetch("/api/characters/jobs"', self.js)
        self.assertIn("/api/characters/jobs/${id}", self.js)
        self.assertIn("/api/characters/jobs/${id}/caption", self.js)
        self.assertIn("/api/characters/jobs/${id}/image", self.js)
        self.assertIn("/api/characters/readiness", self.js)

    def test_repeated_submissions_stay_independent_and_unlocked(self):
        self.assertIn("localStorage", self.js)
        self.assertIn("MAX_STORED", self.js)
        self.assertIn("for (const id of stored().reverse()) watch(id)", self.js)
        # The generate button is disabled only across its own single request.
        self.assertEqual(re.findall(r"button\.disabled = (true|false)", self.js), ["true", "false"])
        self.assertNotRegex(self.js, r"querySelectorAll\(['\"]button['\"]\)")
        self.assertIn("jobsHost.prepend(card)", self.js)

    def test_no_eta_or_hardware_timing_claim(self):
        for name, text in (("page", self.page), ("script", self.js)):
            lowered = text.lower()
            for banned in (r"\beta\b", r"estimated", r"seconds remaining", r"will take", r"average time"):
                with self.subTest(page=name, banned=banned):
                    self.assertNotRegex(lowered, banned)

    def test_shuffle_is_local_and_the_direction_stays_editable(self):
        self.assertIn("Math.random", self.js)
        self.assertIn("directionField.value", self.js)
        self.assertIn('$("#shuffle").addEventListener("click", shuffle)', self.js)
        self.assertIn("clearAxes", self.js)
        shuffle_body = self.js[self.js.index("function shuffle()"):self.js.index("function clearAxes()")]
        self.assertNotIn("fetch(", shuffle_body, "shuffle must never call the server")

    def test_turnaround_wording_never_sends_character_sheet(self):
        self.assertIn("/character sheet/i.test(direction)", self.js)
        self.assertIn("turnaround", self.page.lower())
        self.assertNotIn("character sheet", self.page.lower())

    def test_every_page_loads_the_token_sheet_before_the_sheets_that_consume_it(self):
        """design-system.css is the only file defining the CSS variables, so a page that links
        app.css without it renders with every var(--…) unresolved and looks unstyled."""
        tokens = (SRC / "static" / "design-system.css").read_text()
        self.assertIn(":root", tokens, "the token sheet must define the studio variables")
        for name, markup in (("character.html", self.page), ("index.html", self.index), ("h3.html", self.h3)):
            with self.subTest(page=name):
                token_at = markup.find("design-system.css")
                shell_at = markup.find("app.css")
                self.assertNotEqual(token_at, -1, f"{name} must link the token sheet")
                self.assertNotEqual(shell_at, -1, f"{name} must link the studio shell sheet")
                self.assertLess(token_at, shell_at, f"{name} must load the tokens before app.css")
                for sheet in re.findall(r'href="/static/([a-z-]+\.css)"', markup):
                    with self.subTest(page=name, sheet=sheet):
                        css = (SRC / "static" / sheet).read_text()
                        self.assertTrue(css.strip(), f"{sheet} must not be empty")
                        if sheet != "design-system.css":
                            self.assertIn("var(--", css,
                                          f"{sheet} consumes studio tokens and needs the token sheet")

    def test_served_page_and_assets_resolve(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
                character_studio_app, "_character_readiness",
                return_value={"ready": True, "issues": [], "warnings": []}):
            app = FastAPI()
            app.mount("/static", StaticFiles(directory=str(SRC / "static")), name="static")
            with ThreadPoolExecutor(max_workers=1) as executor:
                character_studio_app.register_optional_characters(app, executor, lambda: Path("."))
                with TestClient(app) as client:
                    page = client.get("/characters")
                    self.assertEqual(page.status_code, 200)
                    self.assertIn("Viral", page.text)
                    for asset in ("/static/character.js", "/static/character.css", "/static/app.css"):
                        self.assertEqual(client.get(asset).status_code, 200, asset)


if __name__ == "__main__":
    unittest.main()
