"""The attempt route queues a durable hunt and never runs GPU work in the request."""
import sys
from pathlib import Path
import tempfile
import os
import unittest
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from continuity_attempt_api import create_router  # noqa: E402
import continuity_attempts as attempts  # noqa: E402

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

    def test_repeated_post_returns_same_attempt_and_starts_worker_once(self):
        url = f'/api/continuity/takes/{TAKE}/attempts'
        first = self.client.post(url, json=BODY)
        second = self.client.post(url, json=BODY)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(self.started, [first.json()['attempt_id']])
        self.assertEqual(set(first.json()), {'attempt_id', 'take_id', 'status', 'error', 'candidates'})

    def test_concurrent_posts_converge_and_only_queue_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: self.client.post(
                f'/api/continuity/takes/{TAKE}/attempts', json=BODY), range(8)))
        self.assertEqual([r.status_code for r in responses], [202] * 8)
        ids = {r.json()['attempt_id'] for r in responses}
        self.assertEqual(len(ids), 1)
        self.assertEqual(self.started, list(ids))

    def test_reusing_request_with_changed_payload_or_take_is_conflict(self):
        url = f'/api/continuity/takes/{TAKE}/attempts'
        first = self.client.post(url, json=BODY)
        for change in ({'prompt': 'Other'}, {'raw_frames': 175}, {'seeds': [2, 1]}):
            with self.subTest(change=change):
                response = self.client.post(url, json=BODY | change)
                self.assertEqual(response.status_code, 409, response.text)
        response = self.client.post('/api/continuity/takes/' + 'c' * 32 + '/attempts', json=BODY)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.started, [first.json()['attempt_id']])
        self.assertEqual(len(list(Path(self.tmp.name).rglob('attempt.json'))), 1)

    def test_router_restart_finds_request_without_requeue(self):
        first = self.client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY).json()
        # A fresh router/worker has no process-local request cache.
        class Worker:
            def start(inner, attempt_id):
                self.fail('An existing request must not be queued after restart')

        app = FastAPI()
        app.include_router(create_router(lambda: Path(self.tmp.name), worker=Worker()))
        with TestClient(app) as client:
            recovered = client.get(f'/api/continuity/takes/{TAKE}/attempts/by-request/' + BODY['request_id'])
            self.assertEqual(recovered.status_code, 200)
            self.assertEqual(recovered.json(), first)
            duplicate = client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY)
            self.assertEqual(duplicate.status_code, 202)
            self.assertEqual(duplicate.json(), first)
        self.assertEqual(len(self.started), 1)

    def test_restart_reconciles_a_real_crash_before_http_recovery_without_requeue(self):
        import multiprocessing
        from unittest.mock import Mock
        from test_continuity_attempts import crash_in_process

        root = Path(self.tmp.name)
        record = attempts.create(root, take_id=TAKE, **BODY)
        process = multiprocessing.get_context('spawn').Process(
            target=crash_in_process, args=(str(root), record['attempt_id']))
        process.start()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join()
            self.fail('Crash test child did not exit')
        self.assertEqual(process.exitcode, 17)
        self.assertEqual([c['status'] for c in attempts.load(root, record['attempt_id'])['candidates']],
                         ['done', 'running'])
        refine, submit = Mock(side_effect=AssertionError), Mock(side_effect=AssertionError)
        worker = attempts.Worker(root, refine=refine, submit=submit)
        app = FastAPI()
        app.include_router(create_router(lambda: root, worker=worker))
        with TestClient(app) as client:
            by_request = f'/api/continuity/takes/{TAKE}/attempts/by-request/' + BODY['request_id']
            recovered = client.get(by_request)
            self.assertEqual(recovered.status_code, 200)
            self.assertEqual(recovered.json()['status'], 'failed')
            self.assertEqual([c['status'] for c in recovered.json()['candidates']], ['done', 'unknown'])
            self.assertEqual(recovered.json()['candidates'][0]['take_id'], 'c' * 32)
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            status = client.get('/api/continuity/attempts/' + record['attempt_id'])
            repeated = client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY)
            self.assertEqual(status.json(), recovered.json())
            self.assertEqual(repeated.json(), recovered.json())
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
        refine.assert_not_called()
        submit.assert_not_called()
        self.assertIsNone(worker._thread)

    def test_restart_recovers_pending_queue_and_real_refiner_crash_without_compute(self):
        import multiprocessing
        from unittest.mock import Mock
        from test_continuity_attempts import crash_in_refine_process

        for phase in ('queued', 'refining'):
            with self.subTest(phase=phase):
                root = Path(self.tmp.name) / phase
                record = attempts.create(root, take_id=TAKE, **BODY)
                if phase == 'refining':
                    child = multiprocessing.get_context('spawn').Process(
                        target=crash_in_refine_process, args=(str(root), record['attempt_id']))
                    child.start()
                    child.join(10)
                    if child.is_alive():
                        child.terminate()
                        child.join()
                        self.fail('Refiner crash child did not exit')
                    self.assertEqual(child.exitcode, 19)
                self.assertEqual(attempts.load(root, record['attempt_id'])['status'], 'pending')
                refine, submit = Mock(side_effect=AssertionError), Mock(side_effect=AssertionError)
                worker = attempts.Worker(root, refine=refine, submit=submit)
                app = FastAPI()
                app.include_router(create_router(lambda: root, worker=worker))
                with TestClient(app) as client:
                    url = f'/api/continuity/takes/{TAKE}/attempts/by-request/' + BODY['request_id']
                    recovered = client.get(url)
                    self.assertEqual(recovered.status_code, 200)
                    self.assertEqual(recovered.json()['status'], 'failed')
                    self.assertEqual([c['status'] for c in recovered.json()['candidates']], ['failed', 'failed'])
                    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    self.assertEqual(client.get('/api/continuity/attempts/' + record['attempt_id']).json(),
                                     recovered.json())
                    self.assertEqual(client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY).json(),
                                     recovered.json())
                    self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
                refine.assert_not_called()
                submit.assert_not_called()
                self.assertIsNone(worker._thread)

    def test_request_lookup_is_read_only_scoped_and_validates_identifiers(self):
        base = f'/api/continuity/takes/{TAKE}/attempts/by-request/'
        self.assertEqual(self.client.get(base + BODY['request_id']).status_code, 404)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        for bad in ('b' * 31, 'B' * 32, 'b' * 32 + '%0A'):
            self.assertEqual(self.client.get(base + bad).status_code, 422)
        self.assertEqual(self.client.get('/api/continuity/takes/bad/attempts/by-request/'
                                         + BODY['request_id']).status_code, 422)
        self.client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY)
        before = {p: p.read_bytes() for p in Path(self.tmp.name).rglob('*') if p.is_file()}
        wrong_take = '/api/continuity/takes/' + 'c' * 32 + '/attempts/by-request/'
        self.assertEqual(self.client.get(wrong_take + BODY['request_id']).status_code, 404)
        self.assertEqual(self.client.get(base + 'd' * 32).status_code, 404)
        self.assertEqual(self.client.get(base + BODY['request_id']).status_code, 200)
        self.assertEqual(before, {p: p.read_bytes() for p in Path(self.tmp.name).rglob('*') if p.is_file()})
        self.assertEqual(len(self.started), 1)

    def test_unreadable_store_is_not_reported_as_unknown_request(self):
        first = self.client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY).json()
        path = attempts._folder(Path(self.tmp.name), first['attempt_id']) / 'attempt.json'
        path.write_text('{broken')
        response = self.client.get(f'/api/continuity/takes/{TAKE}/attempts/by-request/' + BODY['request_id'])
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(path.read_text(), '{broken')

    def test_listing_includes_legacy_attempts_and_reports_truncation_honestly(self):
        root = Path(self.tmp.name)
        legacy = attempts.create(root, take_id=TAKE, prompt='legacy', raw_frames=158, seeds=[1])
        other = attempts.create(root, take_id='c' * 32, prompt='other', raw_frames=158, seeds=[1])
        url = f'/api/continuity/takes/{TAKE}/attempts'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'attempts': [attempts.public(legacy)], 'total': 1, 'has_more': False})
        for _ in range(51):
            attempts.create(root, take_id=TAKE, prompt='legacy', raw_frames=158, seeds=[1])
        body = self.client.get(url).json()
        self.assertEqual(len(body['attempts']), 50)
        self.assertEqual(body['total'], 52)
        self.assertTrue(body['has_more'])
        self.assertNotIn(other['attempt_id'], {a['attempt_id'] for a in body['attempts']})
        self.assertEqual(self.client.get('/api/continuity/takes/bad/attempts').status_code, 422)
        self.assertEqual(self.started, [])

    def test_a_bad_request_is_refused_before_anything_is_queued(self):
        for body in (dict(BODY, seeds=[1, 1]), dict(BODY, seeds=[2 ** 64]),
                     dict(BODY, seeds=[True]), dict(BODY, seeds=['1']),
                     dict(BODY, seeds=[-1]), dict(BODY, seeds=[1, 2, 3, 4, 5]),
                     dict(BODY, seeds=[{}]), dict(BODY, request_id='B' * 32),
                     dict(BODY, request_id='b' * 32 + '\n'),
                     {k: v for k, v in BODY.items() if k != 'request_id'},
                     dict(BODY, raw_frames=158.0), dict(BODY, raw_frames=True),
                     dict(BODY, raw_frames=57), dict(BODY, prompt='   '),
                     dict(BODY, graph='x'), dict(BODY, seeds=[])):
            with self.subTest(body=body):
                response = self.client.post(f'/api/continuity/takes/{TAKE}/attempts', json=body)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.started, [])
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_unknown_and_malformed_attempts_are_404_and_422(self):
        self.assertEqual(self.client.get('/api/continuity/attempts/' + 'c' * 32).status_code, 404)
        # A slash never matches the route, so it is a plain 404 like any unknown path.
        for bad in ('c' * 31, 'C' * 32):
            self.assertEqual(self.client.get('/api/continuity/attempts/' + bad).status_code, 422)

    def _precheck_client(self, check, create):
        from types import SimpleNamespace
        app = FastAPI()
        app.include_router(create_router(
            lambda: Path(self.tmp.name) / 'attempts',
            worker=SimpleNamespace(start=self.started.append), create=create,
            precheck=check, anchored_precheck=check))
        return TestClient(app, raise_server_exceptions=False)

    def test_missing_anchor_real_precheck_is_a_deterministic_refusal(self):
        from unittest.mock import Mock
        from continuity_pipeline import precheck_request
        root = Path(self.tmp.name)
        create = Mock(side_effect=AssertionError('Creation must not run'))
        client = self._precheck_client(lambda take, raw: precheck_request(root, take, raw), create)
        url = f'/api/continuity/takes/{TAKE}/attempts'
        for _ in range(2):
            response = client.post(url, json=BODY)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()['detail'],
                             'The saved anchor could not be read. Select an available saved take and try again. No generation was created.')
        self.assertEqual(client.get(url + '/by-request/' + BODY['request_id']).status_code, 404)
        create.assert_not_called()
        self.assertEqual(self.started, [])
        self.assertEqual(list(root.rglob('*')), [])

    def test_precheck_oserrors_refuse_safely_for_each_anchor_mode(self):
        import errno
        from unittest.mock import Mock, patch
        from continuity_pipeline import precheck_request
        for error in (PermissionError(errno.EACCES, 'PRIVATE secret', '/private/SECRET'),
                      OSError(errno.EIO, 'PRIVATE secret', '/private/SECRET')):
            for extra in ({}, {'reference_ids': ['d' * 32]}, {'mode': 'prepend'},
                          {'mode': 'bridge', 'second_take_id': 'c' * 32}):
                with self.subTest(error=type(error).__name__, extra=extra):
                    create = Mock(side_effect=AssertionError('Creation must not run'))
                    client = self._precheck_client(
                        lambda take, raw, **_: precheck_request(Path(self.tmp.name), take, raw), create)
                    with patch('continuity_pipeline.get_validated_family', side_effect=error):
                        response = client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY | extra)
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertIn('No generation was created.', response.json()['detail'])
                    self.assertNotIn('SECRET', response.text)
                    self.assertNotIn('PRIVATE', response.text)
                    create.assert_not_called()
        self.assertEqual(self.started, [])
        self.assertEqual(list(Path(self.tmp.name).rglob('*')), [])

    def test_only_precheck_oserrors_are_confirmed_refusals(self):
        from unittest.mock import Mock
        for check, create in ((Mock(side_effect=RuntimeError('unexpected bug')), Mock()),
                              (Mock(return_value=None), Mock(side_effect=OSError('uncertain persistence')))):
            with self.subTest(check=check):
                client = self._precheck_client(check, create)
                response = client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY)
                self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(self.started, [])

    def test_an_unconfigured_instance_refuses_variants(self):
        app = FastAPI()
        app.include_router(create_router(lambda: Path(self.tmp.name), worker=None))
        with TestClient(app) as client:
            response = client.post(f'/api/continuity/takes/{TAKE}/attempts', json=BODY)
        self.assertEqual(response.status_code, 503)


if __name__ == '__main__':
    unittest.main()
