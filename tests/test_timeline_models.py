"""Strict public edit payloads; no coercion of revisions or frame offsets."""
import unittest
from pydantic import ValidationError
from timeline_models import CreateProject, EditProject, ImportJob, ExportProject


class TimelineModelsTests(unittest.TestCase):
    def test_create_empty_and_optional_context(self):
        self.assertEqual(CreateProject(title="Cut").title, "Cut")
        self.assertIsNone(CreateProject(title="Cut").character_id)

    def test_reject_dirty_payloads(self):
        for payload in ({"title": ""}, {"title": "x", "path": "/tmp/a"},
                        {"title": "x", "character_id": "../other"}, {"title": "a" * 161}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                CreateProject(**payload)
        for value in (True, "1", -1, 1.5):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ExportProject(revision=value)
        with self.assertRaises(ValidationError):
            ImportJob(revision=0, job_id="H" * 32)
        for payload in ({"revision": 0, "clips": [{"clip_id": "a" * 32, "in_frame": True, "out_frame": 4}]},
                        {"revision": 0, "clips": [], "take_path": "x"}):
            with self.assertRaises(ValidationError):
                EditProject(**payload)


if __name__ == "__main__":
    unittest.main()
