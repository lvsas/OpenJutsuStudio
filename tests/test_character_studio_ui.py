"""Character stage interface contracts: navigation order, payload shape, no locks, no ETA."""
import os
import re
import subprocess
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

    def test_character_hero_keeps_the_shared_studio_hierarchy(self):
        match = re.search(r'<section class="studio-intro"[^>]*>(.*?)</section>', self.page, re.S)
        assert match is not None, 'Characters must expose the shared hero'
        intro = match.group(1)
        self.assertIn('<p class="eyebrow">Viral character creation</p>', intro)
        self.assertIn('<h1>Make a character.<br><em>Give them a viral signature.</em></h1>', intro)
        for markup in (self.index, self.h3):
            self.assertRegex(markup, r'<h1[^>]*>[^<]+<br><em>[^<]+</em></h1>')
        for rule in re.findall(r'\.studio-intro[^{}]*\{([^{}]*)\}', self.css):
            self.assertNotRegex(rule, r'font-size|line-height|padding|gap|letter-spacing',
                                'Characters must inherit shared hero typography and spacing')
        self.assertNotRegex(self.css, r'\.studio-shell\s*\{', 'keep the shared outer gutter')

    def test_primary_action_precedes_optional_refinements(self):
        self.assertEqual(self.page.count('id="generate"'), 1)
        self.assertLess(self.page.index('id="direction"'), self.page.index('id="generate"'))
        self.assertLess(self.page.index('id="generate"'), self.page.index('id="refine-list"'))
        editor = re.search(r'<label[^>]*id="direction-editor"[^>]*>', self.page)
        assert editor is not None, 'the idea must stay editable'
        self.assertNotIn('hidden', editor.group(0))
        self.assertNotRegex(self.css, r'position:\s*(?:fixed|sticky)', 'no overlay to rescue CTA reachability')

    def test_page_loads_the_studio_shell_and_its_own_assets(self):
        self.assertIn("/static/app.css", self.page)
        self.assertIn("/static/character.css", self.page)
        self.assertIn("/static/character.js", self.page)
        self.assertIn('data-engine="characters"', self.page)
        self.assertIn("Viral", self.page)
        self.assertNotIn("<style>", self.page, "the page must use the shared stylesheet, not inline CSS")
        self.assertNotIn("style=", self.page)

    def test_refine_proposal_is_progressive_and_keeps_the_taxonomy_out_of_the_default_flow(self):
        """The selected B sketch starts from one person, then exposes only four named changes."""
        self.assertNotIn("🔒", self.page + self.js)
        self.assertNotIn("padlock", (self.page + self.js).lower())
        self.assertNotRegex(self.css, r"\.locked|\.is-locked")
        for element_id in ("proposal-summary", "refine-list", "refine-options", "more-control"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.page)
        for label in ("Silhouette", "Signature hair and face", "Expression and personality",
                      "Clothes and style"):
            with self.subTest(label=label):
                self.assertIn(f'"{label}"', self.js)
        self.assertIn("const REFINEMENTS = [", self.js)
        self.assertIn("function renderRefinements()", self.js)
        self.assertIn("function renderRefineOptions()", self.js)
        self.assertIn("openRefinement === key ? null : key", self.js,
                      "opening a refinement must close the same drawer, and rendering closes others")
        self.assertIn("refineOptionsHost.replaceChildren()", self.js)
        self.assertIn('input.type = "text"', self.js, "free text must stay possible within a refinement")
        self.assertIn("axisValues.delete(key)", self.js, "every selected value needs a one-action clear")
        # More control is a native disclosure and stays closed until explicitly requested.
        details = re.search(r"<details[^>]*id=\"more-control\"[^>]*>", self.page)
        self.assertIsNotNone(details, "advanced controls need a native disclosure")
        self.assertNotIn(" open", details.group(0))
        self.assertGreater(self.page.index('id="more-control"'), self.page.index('id="refine-options"'))
        # Generic axes exist only inside the advanced disclosure, never as the default visual flow.
        self.assertGreater(self.page.index('id="axis-picker"'), self.page.index('id="more-control"'))
        for axis in ("being", "build", "skin_tone", "hair", "face", "outfit", "role", "era", "attitude"):
            self.assertIn(f'"{axis}"', self.js, f"{axis} must be part of the v2 optional vocabulary")
        for removed_axis in ("accessory", "absurdity"):
            self.assertNotIn(f'"{removed_axis}"', self.js, f"v2 must not expose {removed_axis}")
        self.assertIn(".more-control:not([open]) > :not(summary) { display: none; }", self.css,
                      "a closed advanced disclosure must actually hide its controls")

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
        # Execute the shipped script: queued work must not clear the selected canvas,
        # writes must be verified, and discarded in-flight responses must stay discarded.
        result = subprocess.run(["node", "--test", "tests/character_workspace.test.cjs",
                                 "tests/character_variety.test.cjs"],
                                cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.page.count('id="active-result"'), 1)
        self.assertNotIn('class="job-card"', self.page)
        for disclosure in ("recent-attempts", "more-details", "use-character"):
            match = re.search(r'<details[^>]*id="' + disclosure + r'"[^>]*>', self.page)
            self.assertIsNotNone(match)
            self.assertNotIn(" open", match.group(0))
        self.assertIn('href="/timeline"', nav_of(self.page))

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

    def test_payload_records_whether_the_direction_was_generated_or_user_authored(self):
        self.assertIn('let directionOrigin = "generated"', self.js)
        start = self.js.index("function shuffle()")
        end = self.js.index("/* ----", start)
        self.assertIn('directionOrigin = "generated"', self.js[start:end])
        self.assertRegex(self.js, r'directionField\.addEventListener\("input", \(\) => \{\s*directionOrigin = "user_authored";')
        self.assertRegex(self.js, r"direction_origin:\s*directionOrigin")

    def test_shuffle_vocabulary_is_person_first_face_safe_and_style_coherent(self):
        """A viral hook comes from one complete contemporary look, never a prop or costume collision."""
        banned_default_terms = (
            "taxidermy", "accordion", "oversized ring of keys", "bolted-on grin",
            "eyebrows drawn far too high", "gormless", "holding a fish", "competitive cheese judge",
            "night-shift lighthouse keeper", "unlicensed beekeeper", "freelance snake handler",
            "towering pompadour", "blunt bowl cut", "puffer jacket over a wetsuit",
            "tuxedo with shorts", "hi-vis vest over full evening dress", "raincoat two sizes too small",
        )
        for term in banned_default_terms:
            with self.subTest(term=term):
                self.assertNotIn(term, self.js.lower(), f"default shuffle contains stale prop-comedy term: {term!r}")
        self.assertNotIn("const PROPS", self.js, "default shuffle must not define a props vocabulary")
        self.assertNotIn("const ROLES", self.js, "independent lists create incoherent costume collisions")
        self.assertNotIn('"accessory"', self.js, "browser controls must not expose accessory")
        self.assertIn("const LOOKS = [", self.js)
        direction_start = self.js.index("function buildDirection()")
        direction_end = self.js.index("function shuffle()", direction_start)
        direction_builder = self.js[direction_start:direction_end]
        self.assertIn("const look = pick(LOOKS)", direction_builder)
        for field in ("being", "role", "build", "hair", "face", "outfit", "attitude"):
            with self.subTest(field=field):
                self.assertIn(f"look.{field}", direction_builder)
        for signal in ("realistically proportioned", "jaw-length dense copper bob", "geometric silver", "horizontal black rolls", "sculptural", "moustache", "smirk"):
            with self.subTest(signal=signal):
                self.assertIn(signal, self.js.lower(), f"default looks lost physical/personality hook: {signal!r}")
        self.assertIn("An original adult ${look.being},", direction_builder)
        self.assertNotIn("caricature", direction_builder)
        self.assertNotRegex(self.js, r"outsized head|tiny waist|spindly legs")
        self.assertNotRegex(direction_builder, r"editorial|street.style|photograph|studio|portrait")
        self.assertNotRegex(direction_builder, r"\b(?:holding|carrying|clutching|cradling|wheeling|balancing)\b")

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

    def test_each_surface_owns_one_distinct_accent(self):
        """Three surfaces, three accents: the shared lime belongs to the Character Generator.

        LTX and the character stage previously resolved to the same lime, so nothing on screen
        said which studio you were in. Each studio sheet now overrides the token for its own
        ``data-engine`` scope, and the shared sheet keeps the default the generator uses.
        """
        shared = (SRC / "static" / "design-system.css").read_text()
        self.assertIn("--accent: #d8ff3e", shared, "the shared default stays the generator's lime")
        for name, markup in (("index.html", self.index), ("h3.html", self.h3),
                             ("character.html", self.page)):
            with self.subTest(page=name):
                self.assertIn("design-system.css", markup)
        scoped = {"ltx": "#22d3ee", "h3": "#ff4f2e"}
        for engine, accent in scoped.items():
            with self.subTest(engine=engine):
                sheet = (SRC / "static" / f"{engine}-studio.css").read_text()
                self.assertIn(f'html[data-engine="{engine}"]', sheet)
                self.assertIn(f"--accent: {accent}", sheet)
                markup = self.index if engine == "ltx" else self.h3
                self.assertIn(f'href="/static/{engine}-studio.css"', markup)
                # The override must load after the shared tokens and the shell it adjusts.
                self.assertLess(markup.find("design-system.css"), markup.find(f"{engine}-studio.css"))
                self.assertLess(markup.find("app.css"), markup.find(f"{engine}-studio.css"))
        self.assertNotIn("--accent:", (SRC / "static" / "character.css").read_text(),
                         "the generator must keep inheriting the shared lime, not fork it")

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
