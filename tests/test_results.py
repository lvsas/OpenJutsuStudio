"""Video results support inline playback, explicit download and seeking."""
from pathlib import Path
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
