"""Isolated HTTP contract tests, including actual uploads and byte ranges."""
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_timeline_store import IsolatedTimeline, make_video
from timeline_api import create_router


class TimelineApiTests(IsolatedTimeline):
    def setUp(self):
        super().setUp()
        self.app = FastAPI()
        self.app.include_router(create_router(lambda: self.work, lambda: self.media, 2_000_000))
        self.client = self.enterContext(TestClient(self.app))

    def create(self):
        result = self.client.post("/api/timeline/projects", json={"title": "Sequence"})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def test_project_api_dirty_payload_conflict_and_restart(self):
        project = self.create()
        url = "/api/timeline/projects/" + project["project_id"]
        self.assertEqual(self.client.get(url).json(), project)
        self.assertEqual(self.client.get("/api/timeline/projects").json()["projects"][0]["project_id"], project["project_id"])
        for revision in (True, "0", -1):
            response = self.client.patch(url, json={"revision": revision, "clips": []})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.patch(url, json={"revision": 0, "clips": [], "path": "x"}).status_code, 422)
        self.assertEqual(self.client.patch(url, json={"revision": 0, "title": "New", "clips": []}).status_code, 200)
        self.assertEqual(self.client.patch(url, json={"revision": 0, "clips": []}).status_code, 409)
        for bad in ("bad", "a" * 31, "A" * 32):
            self.assertEqual(self.client.get("/api/timeline/projects/" + bad).status_code, 422)
        for payload in ({"title": "x", "take_path": "x"}, {"title": "x", "character_id": "../../secret"}):
            self.assertEqual(self.client.post("/api/timeline/projects", json=payload).status_code, 422)
        app = FastAPI()
        app.include_router(create_router(lambda: self.work, lambda: self.media, 2_000_000))
        with TestClient(app) as client:
            self.assertEqual(client.get(url).json()["title"], "New")

    def test_upload_range_disposition_job_import_and_real_export(self):
        project = self.create()
        source = make_video(self.media / "fixture.mp4", audio=True)
        url = f"/api/timeline/projects/{project['project_id']}"
        data = source.read_bytes()
        response = self.client.post(url + "/imports", data={"revision": "0"},
                                    files={"file": ("../../private.mp4", data, "video/mp4")})
        self.assertEqual(response.status_code, 201, response.text)
        project = response.json()
        clip = project["clips"][0]
        self.assertIsNone(clip["source_job_id"])
        self.assertEqual(clip["label"], "Imported video")
        self.assertNotIn(str(self.work), response.text)
        response = self.client.get(clip["media_url"], headers={"Range": "bytes=0-15"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, data[:16])
        self.assertTrue(response.headers["content-disposition"].startswith("inline;"))
        response = self.client.get(clip["media_url"] + "?download=true")
        self.assertTrue(response.headers["content-disposition"].startswith("attachment;"))
        self.assertEqual(response.content, data)
        job = self.job(source)
        response = self.client.post(url + "/clips", json={"revision": 1, "job_id": job.id})
        self.assertEqual(response.status_code, 201, response.text)
        project = response.json()
        self.assertEqual(project["clips"][1]["source_job_id"], job.id)
        result = self.client.post(url + "/export", json={"revision": 2})
        self.assertEqual(result.status_code, 202, result.text)
        result = result.json()
        self.assertIsNone(result["preview_url"])
        for _ in range(200):
            result = self.client.get(result["status_url"]).json()
            if result["status"] not in ("queued", "running"):
                break
            time.sleep(.02)
        self.assertEqual(result["status"], "ready", result)
        repeat = self.client.post(url + "/export", json={"revision": 2})
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.json()["export_id"], result["export_id"])
        response = self.client.get(result["download_url"], headers={"Range": "bytes=0-7"})
        self.assertEqual(response.status_code, 206)
        self.assertTrue(response.headers["content-disposition"].startswith("attachment;"))

    def test_same_revision_export_retry_after_error_needs_no_retry_flag(self):
        from unittest.mock import patch
        project = self.create()
        source = make_video(self.media / "retry.mp4")
        url = f"/api/timeline/projects/{project['project_id']}"
        project = self.client.post(url + "/clips", json={"revision": 0, "job_id": self.job(source).id}).json()
        def await_status(result):
            for _ in range(200):
                result = self.client.get(result["status_url"]).json()
                if result["status"] not in ("queued", "running"):
                    return result
                time.sleep(.02)
            self.fail("Export attempt did not finish")
        with patch("timeline_export.render_snapshot", side_effect=RuntimeError("/private/error")):
            failed = self.client.post(url + "/export", json={"revision": 1})
            self.assertEqual(failed.status_code, 202, failed.text)
            failed = await_status(failed.json())
            self.assertEqual(failed["status"], "error")
        retried = self.client.post(url + "/export", json={"revision": 1})
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertNotEqual(retried.json()["export_id"], failed["export_id"])
        ready = await_status(retried.json())
        self.assertEqual(ready["status"], "ready", ready)
        self.assertEqual(ready["preview_url"], f"/api/timeline/exports/{ready['export_id']}/media")
        self.assertEqual(ready["download_url"], ready["preview_url"] + "?download=true")
        self.assertEqual(self.client.get(failed["status_url"]).json()["status"], "error")

    def test_bad_upload_and_bounded_chunked_body(self):
        project = self.create()
        url = f"/api/timeline/projects/{project['project_id']}/imports"
        for data in (b"not mp4", b"#EXTM3U\nhttp://127.0.0.1:1/a\n"):
            response = self.client.post(url, data={"revision": "0"}, files={"file": ("a.mp4", data)})
            self.assertEqual(response.status_code, 422, response.text)
        response = self.client.post(url, data={"revision": "true"}, files={"file": ("a.mp4", b"x")})
        self.assertEqual(response.status_code, 422)
        response = self.client.post(url, data={"revision": "0", "path": "/secret"}, files={"file": ("a.mp4", b"x")})
        self.assertEqual(response.status_code, 422)
        boundary = "test-boundary"
        def body():
            yield (f"--{boundary}\r\nContent-Disposition: form-data; name=\"revision\"\r\n\r\n0\r\n"
                   f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.mp4\"\r\n\r\n").encode()
            for _ in range(33):
                yield b"x" * 65536
            yield f"\r\n--{boundary}--\r\n".encode()
        response = self.client.post(url, content=body(), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(self.client.get(f"/api/timeline/projects/{project['project_id']}").json()["revision"], 0)
        self.assertEqual(list((self.work / "timeline" / "staging").iterdir()), [])
