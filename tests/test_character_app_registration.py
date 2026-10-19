"""Character page and API register by default and can be explicitly disabled."""
import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import character_studio_app  # noqa: E402


class CharacterAppRegistrationTests(unittest.TestCase):
    def test_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
                character_studio_app, "_character_readiness",
                return_value={"ready": True, "issues": [], "warnings": []}):
            app = FastAPI()
            with ThreadPoolExecutor(max_workers=1) as executor:
                self.assertTrue(character_studio_app.register_optional_characters(
                    app, executor, lambda: Path(".")))
                with TestClient(app) as client:
                    self.assertEqual(client.get("/characters").status_code, 200)
                    self.assertTrue(client.get("/api/characters/readiness").json()["ready"])

    def test_can_be_explicitly_disabled(self):
        for value in ("0", "false", "no", "off"):
            with self.subTest(value=value), patch.dict(
                    os.environ, {"OPENGENJUTSU_CHARACTER_STUDIO_ENABLED": value}, clear=True):
                app = FastAPI()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    self.assertFalse(character_studio_app.register_optional_characters(
                        app, executor, lambda: Path(".")))
                    with TestClient(app) as client:
                        self.assertEqual(client.get("/characters").status_code, 404)
                        self.assertEqual(client.get("/api/characters/readiness").status_code, 404)

    def test_enabled_registration_exposes_the_character_stage_only(self):
        with patch.dict(os.environ, {"OPENGENJUTSU_CHARACTER_STUDIO_ENABLED": "true"}, clear=True), \
                patch.object(character_studio_app, "_character_readiness", return_value={
                    "ready": False, "issues": ["FLUX 3 weights missing"], "warnings": []}):
            app = FastAPI()
            with ThreadPoolExecutor(max_workers=1) as executor:
                self.assertTrue(character_studio_app.register_optional_characters(
                    app, executor, lambda: Path(".")))
                with TestClient(app) as client:
                    page = client.get("/characters")
                    self.assertEqual(page.status_code, 200)
                    self.assertIn("Viral Character Maker", page.text)
                    self.assertIn('data-engine="characters"', page.text)
                    report = client.get("/api/characters/readiness")
                    self.assertEqual(report.status_code, 200)
                    self.assertEqual(report.json()["issues"], ["FLUX 3 weights missing"])
                    self.assertEqual(client.get("/api/characters/jobs/missing/image").status_code, 404)

    def test_readiness_uses_the_pinned_character_graph(self):
        captured = {}

        def fake_check(required_graph=None):
            captured["graph"] = required_graph
            return {"ready": True, "issues": [], "warnings": []}

        with patch("readiness.check_readiness", side_effect=fake_check):
            report = character_studio_app._character_readiness()
        self.assertTrue(report["ready"])
        graph = captured["graph"]
        self.assertEqual(len(graph), 20)
        self.assertIn("character_caption", graph)
        self.assertEqual(graph["18:7"]["class_type"], "KSampler")


if __name__ == "__main__":
    unittest.main()
