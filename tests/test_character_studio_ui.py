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

    def test_optional_control_is_collapsed_and_reveals_one_axis_at_a_time(self):
        """Density was the failure: every axis and option on screen at once. The picker stays a
        single small row and opening an axis reveals only that axis."""
        self.assertNotIn("🔒", self.page + self.js)
        self.assertNotIn("padlock", (self.page + self.js).lower())
        self.assertNotRegex(self.css, r"\.locked|\.is-locked")
        # One host for the options, not one container per axis.
        self.assertEqual(self.js.count('$("#axis-options")'), 1)
        self.assertIn("optionsHost.replaceChildren()", self.js)
        self.assertIn("openAxis === key ? null : key", self.js, "clicking the open axis must close it")
        # Collapsed by default: a closed <details> with no `open` attribute.
        details = re.search(r"<details[^>]*class=\"optional-block\"[^>]*>", self.page)
        self.assertIsNotNone(details, "the optional control must be a native disclosure")
        self.assertNotIn(" open", details.group(0))
        for axis in ("being", "build", "skin_tone", "hair", "face", "outfit", "role", "era",
                     "accessory", "absurdity"):
            self.assertIn(f'"{axis}"', self.js, f"{axis} must be part of the optional vocabulary")
        # A chip is a selection, and selecting it again clears it — never a lock.
        self.assertIn("axisValues.get(openAxis) === choice ? \"\" : choice", self.js)
        self.assertIn('input.type = "text"', self.js, "a custom value must stay possible")
        # Density guard: setting `display` on a child of <details> overrides the UA rule that hides
        # a closed panel, so the collapsed state must re-hide its content explicitly.
        self.assertIn(".optional-block:not([open]) > :not(summary) { display: none; }", self.css,
                      "a closed optional panel must actually hide its controls")

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
        start = self.js.index("function shuffle()")
        end = self.js.index("/* ----", start)
        shuffle_body = self.js[start:end]
        self.assertNotIn("fetch(", shuffle_body, "shuffle must never call the server")
        self.assertIn("buildDirection()", shuffle_body)

    @unittest.expectedFailure
    def test_next_shuffle_vocabulary_is_person_first_and_face_safe(self):
        """This deliberately fails on v1: a viral character is a person with a hook, not a prop
        plus an intentionally damaged expression. The v2 implementation must satisfy it before a
        visual GPU acceptance run is allowed. Remove expectedFailure when v2 is implemented: an
        unexpected pass then proves the guardrail is ready to become mandatory."""
        banned_default_terms = (
            "taxidermy", "accordion", "oversized ring of keys", "bolted-on grin",
            "eyebrows drawn far too high", "gormless", "holding a fish",
        )
        for term in banned_default_terms:
            with self.subTest(term=term):
                self.assertFalse(term in self.js.lower(), f"default shuffle contains banned term: {term!r}")
        self.assertFalse("const PROPS" in self.js, "default shuffle must not define a props vocabulary")
        self.assertFalse('"accessory"' in self.js, "v2 browser controls must not expose accessory")
        direction_start = self.js.index("function buildDirection()")
        direction_end = self.js.index("function shuffle()", direction_start)
        direction_builder = self.js[direction_start:direction_end]
        self.assertIn("pick(ROLES)", direction_builder)
        self.assertIn("pick(HOOKS)", direction_builder)
        self.assertIn("pick(OUTFITS)", direction_builder)
        self.assertIn("pick(ATTITUDES)", direction_builder)
        self.assertIn("pick(STANCES)", direction_builder)

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
