"""Video results support inline playback, explicit download and seeking."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app


class ResultTests(unittest.TestCase):
    def test_inline_download_and_range_responses(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app.core, "WORK", Path(tmp)):
            path = Path(tmp) / "result.mp4"
            path.write_bytes(b"0123456789")
            job = app.core.Job(id="result-job", status="done", result=str(path))
            job.save()
            client = TestClient(app.app)
            route = "/api/jobs/result-job/result"
            result = client.get(route)
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.headers["content-disposition"].startswith("inline;"))
            download = client.get(route + "?download=true")
            self.assertTrue(download.headers["content-disposition"].startswith("attachment;"))
            part = client.get(route, headers={"Range": "bytes=0-3"})
            self.assertEqual(part.status_code, 206)
            self.assertEqual(part.content, b"0123")

    def test_completed_job_builds_and_downloads_local_comparison_reel(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app.core, "WORK", Path(tmp)), \
                patch.object(app, "MEDIA_DIR", Path(tmp) / "media"), \
                patch("output_media.REEL_ASSET_DIR", Path(tmp) / "artwork"):
            root = Path(tmp)
            source, result = root / "source.mp4", root / "result.mp4"
            for path, color in ((source, "navy"), (result, "teal")):
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                                f"color=c={color}:size=64x64:rate=24:duration=1", "-c:v", "libx264", str(path)],
                               check=True)
            job = app.core.Job(id="reveal-job", status="done", video=str(source), result=str(result))
            job.save()
            client = TestClient(app.app)
            created = client.post("/api/jobs/reveal-job/reveal")
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(created.json()["status"], "ready")
            self.assertEqual(created.json()["layout"], "wipe")
            self.assertEqual(created.json()["reveal_url"], created.json()["preview_url"])
            self.assertIn("/reels/", created.json()["reveal_url"])
            downloaded = client.get(created.json()["reveal_url"] + "?download=true")
            self.assertEqual(downloaded.status_code, 200)
            self.assertTrue(downloaded.headers["content-disposition"].startswith("attachment;"))
            self.assertGreater(len(downloaded.content), 1_000)

    def test_reveal_rejects_incomplete_job(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app.core, "WORK", Path(tmp)):
            job = app.core.Job(id="not-ready")
            job.save()
            response = TestClient(app.app).post("/api/jobs/not-ready/reveal")
            self.assertEqual(response.status_code, 409)
