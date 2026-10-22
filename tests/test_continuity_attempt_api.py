"""The attempt route queues a durable hunt and never runs GPU work in the request."""
import sys
from pathlib import Path
import tempfile
import os
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from continuity_attempt_api import create_router  # noqa: E402

TAKE = 'a' * 32
BODY = {'request_id': 'b' * 32, 'prompt': 'Keep the motion', 'raw_frames': 158,
        'seeds': [1, 2]}


class AttemptRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.started = []

        class FakeWorker:
            def start(inner, attempt_id):
                self.started.append(attempt_id)

        app = FastAPI()
        app.include_router(create_router(lambda: Path(self.tmp.name), worker=FakeWorker()))
        self.client = TestClient(app)

    def test_a_request_is_queued_and_returns_a_durable_record(self):
        response = self.client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY)
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body['status'], 'pending')
        self.assertEqual([c['status'] for c in body['candidates']], ['pending', 'pending'])
        self.assertEqual(self.started, [body['attempt_id']])
        again = self.client.get(f"/api/continuity/attempts/{body['attempt_id']}")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()['attempt_id'], body['attempt_id'])

    def test_a_bad_request_is_refused_before_anything_is_queued(self):
        for body in (dict(BODY, seeds=[1, 1]), dict(BODY, seeds=[2 ** 64]),
                     dict(BODY, raw_frames=57), dict(BODY, prompt='   '),
                     dict(BODY, graph='x'), dict(BODY, seeds=[])):
            with self.subTest(body=body):
                response = self.client.post(f'/api/continuity/takes/{TAKE}/attempts', json=body)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.started, [])

    def test_unknown_and_malformed_attempts_are_404_and_422(self):
        self.assertEqual(self.client.get('/api/continuity/attempts/' + 'c' * 32).status_code, 404)
        # A slash never matches the route, so it is a plain 404 like any unknown path.
        for bad in ('c' * 31, 'C' * 32):
            self.assertEqual(self.client.get('/api/continuity/attempts/' + bad).status_code, 422)

    def test_an_unconfigured_instance_refuses_variants(self):
        app = FastAPI()
        app.include_router(create_router(lambda: Path(self.tmp.name), worker=None))
        with TestClient(app) as client:
            response = client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY)
        self.assertEqual(response.status_code, 503)


if __name__ == '__main__':
    unittest.main()
