"""CPU-only parentless intent, shared Worker callbacks, and strict root HTTP."""
import copy
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, call, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_attempts as attempts
import continuity_root_api as api
from continuity_attempt_api import create_router as attempt_router
from continuity_root_pipeline import MAX_REFERENCE_BYTES, resolve_root_references, validate_image

CONTEXT = {'reference_ids': ['a' * 32, 'b' * 32], 'width': 960, 'height': 544}
BODY = {'request_id': 'c' * 32, 'prompt': 'Keep both characters walking',
        'raw_frames': 192, 'seeds': [0, 2 ** 64 - 1]}


def image_bytes(color='red', format='PNG', metadata=False):
    buffer = BytesIO()
    options = {}
    if metadata and format == 'PNG':
        info = PngImagePlugin.PngInfo()
        info.add_text('prompt', 'PRIVATE_PROMPT')
        options['pnginfo'] = info
    Image.new('RGB', (32, 32), color=color).save(buffer, format=format, **options)
    return buffer.getvalue()


class RootFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name) / 'work'
        self.root = Path(self.tmp.name) / 'attempts'

    def make(self, **changes):
        return attempts.create_or_get(self.root, **(
            dict(take_id=None, mode='root', root_context=copy.deepcopy(CONTEXT)) | BODY | changes))


class RootAttemptsTests(RootFixture):
    def test_explicit_parentless_record_freezes_a_copy_and_public_has_no_private_data(self):
        context = copy.deepcopy(CONTEXT)
        record, created = self.make(root_context=context)
        context['reference_ids'].reverse()
        self.assertTrue(created)
        self.assertIsNone(record['take_id'])
        self.assertEqual(record['root_context'], CONTEXT)
        self.assertNotIn('second_take_id', record)
        self.assertEqual(attempts.load(self.root, record['attempt_id']), record)
        public = attempts.public(record | {'error': '/private/SECRET prompt'})
        self.assertEqual(set(public), {'attempt_id', 'take_id', 'mode', 'status', 'error', 'candidates'})
        self.assertEqual((public['take_id'], public['mode']), (None, 'root'))
        self.assertNotIn('PRIVATE', json.dumps(public))
        self.assertNotIn('/private/', json.dumps(public))
        self.assertNotIn('prompt', public)
        self.assertNotIn('root_context', public)

    def test_idempotency_freezes_reference_order_size_and_shared_common_intent(self):
        original, _ = self.make()
        self.assertEqual(self.make(), (original, False))
        variants = [{'root_context': CONTEXT | {'reference_ids': list(reversed(CONTEXT['reference_ids']))}},
                    {'root_context': CONTEXT | {'width': 1024}},
                    {'root_context': CONTEXT | {'height': 576}},
                    {'prompt': 'Different'}, {'seeds': [3]}, {'raw_frames': 158},
                    {'take_id': 'd' * 32, 'mode': 'forward', 'root_context': None}]
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises(attempts.AttemptConflict):
                self.make(**changes)
        self.assertEqual(len(list(self.root.rglob('attempt.json'))), 1)

    def test_root_only_no_faked_take_no_second_parent_no_arbitrary_context(self):
        variants = [{'take_id': 'd' * 32}, {'second_take_id': 'e' * 32}, {'root_context': None},
                    {'root_context': CONTEXT | {'graph': {}}},
                    {'mode': 'forward', 'take_id': 'd' * 32},
                    {'root_context': CONTEXT | {'reference_ids': []}}]
        variants += [{'root_context': CONTEXT | {'reference_ids': [id]}} for id in
                     ['../image', 'a' * 31, 'A' * 32, 'a' * 32 + '\n', True, 123]]
        variants += [{'root_context': CONTEXT | {key: val}}
                     for key in ('width', 'height') for val in (True, 31, 33, 2080, 960.0, '960')]
        variants += [{'seeds': val} for val in ([True], [0, 0], [-1], [2 ** 64], [], [1, 2, 3, 4, 5])]
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises(attempts.AttemptError):
                self.make(**changes)
        self.assertFalse(self.root.exists())

    def test_shared_run_callbacks_exact_root_keywords_once_and_retry_only_failed_candidate(self):
        record, _ = self.make()
        refine = Mock(return_value='private prepared text ' * 220)
        submit = Mock(side_effect=['d' * 32, ValueError('first failure')])
        first = attempts.run(self.root, record['attempt_id'], refine=refine, submit=submit)
        self.assertEqual([c['status'] for c in first['candidates']], ['done', 'failed'])
        refine.assert_called_once_with(BODY['prompt'], None, mode='root', root_context=CONTEXT)
        self.assertEqual(submit.call_args_list, [
            call(c['operation_id'], refine.return_value, c['seed'], 192, None,
                 mode='root', root_context=CONTEXT) for c in record['candidates']])
        retry = Mock(return_value='e' * 32)
        second = attempts.run(self.root, record['attempt_id'], refine=refine, submit=retry)
        self.assertEqual(second['status'], 'done')
        self.assertEqual(refine.call_count, 1)
        retry.assert_called_once_with(record['candidates'][1]['operation_id'], refine.return_value,
                                     2 ** 64 - 1, 192, None, mode='root', root_context=CONTEXT)
        attempts.run(self.root, record['attempt_id'], refine=refine, submit=retry)
        self.assertEqual(retry.call_count, 1)

    def test_invalid_persisted_root_intent_cannot_reach_a_compute_callback(self):
        record, _ = self.make()
        path = attempts._folder(self.root, record['attempt_id']) / 'attempt.json'
        refine, submit = Mock(), Mock()
        for changes in ({'take_id': 'd' * 32}, {'second_take_id': 'e' * 32},
                        {'mode': 'forward'}, {'root_context': None},
                        {'root_context': CONTEXT | {'reference_ids': ['../bad']}},
                        {'root_context': CONTEXT | {'width': True}}):
            attempts._atomic(path, record | changes)
            with self.subTest(changes=changes), self.assertRaises(attempts.AttemptError):
                attempts.run(self.root, record['attempt_id'], refine=refine, submit=submit)
        refine.assert_not_called()
        submit.assert_not_called()

    def test_callbacks_cannot_mutate_the_frozen_context_or_later_candidate(self):
        record, _ = self.make()
        def refine(prompt, parent, *, mode, root_context):
            root_context['reference_ids'].clear()
            return 'prepared'
        seen = []
        def submit(*args, **kwargs):
            seen.append(copy.deepcopy(kwargs))
            kwargs['root_context']['reference_ids'].clear()
            return 'd' * 32
        attempts.run(self.root, record['attempt_id'], refine=refine, submit=submit)
        self.assertEqual(seen, [{'mode': 'root', 'root_context': CONTEXT}] * 2)
        self.assertEqual(attempts.load(self.root, record['attempt_id'])['root_context'], CONTEXT)

    def test_same_worker_serializes_root_with_anchored_work(self):
        root, _ = self.make()
        forward = attempts.create(self.root, take_id='d' * 32,
                                  **(BODY | {'request_id': 'e' * 32, 'seeds': [7]}))
        entered, release = threading.Event(), threading.Event()
        seen = []
        def refine(prompt, parent, **kwargs):
            seen.append(('refine', parent, kwargs))
            if kwargs.get('mode') == 'root':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('test release timed out')
            return 'prepared'
        def submit(*args, **kwargs):
            seen.append(('submit', args[-1], kwargs))
            return 'f' * 32
        worker = attempts.Worker(self.root, refine=refine, submit=submit)
        worker.start(root['attempt_id'])
        thread = worker._thread
        try:
            self.assertTrue(entered.wait(5))
            worker.start(forward['attempt_id'])
            worker.start(root['attempt_id'])
            self.assertEqual(worker._queue, [forward['attempt_id']])

        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual([event[:2] for event in seen], [
            ('refine', None), ('submit', None), ('submit', None),
            ('refine', 'd' * 32), ('submit', 'd' * 32)])
        self.assertEqual(seen[-1][2], {})
        self.assertTrue(all(attempts.load(self.root, a['attempt_id'])['status'] == 'done'
                            for a in (root, forward)))

    def test_root_recovery_scoped_read_only_and_startup_reconciliation_does_not_compute(self):
        record, _ = self.make()
        record.update(status='running', refined_prompt='private')
        record['candidates'][0].update(status='done', take_id='d' * 32)
        record['candidates'][1]['status'] = 'running'
        attempts._atomic(attempts._folder(self.root, record['attempt_id']) / 'attempt.json', record)
        refine, submit = Mock(), Mock()
        worker = attempts.Worker(self.root, refine=refine, submit=submit)
        self.assertEqual(worker.reconcile(), [record['attempt_id']])
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        recovered = attempts.root_by_request(self.root, BODY['request_id'])
        self.assertEqual([c['status'] for c in recovered['candidates']], ['done', 'unknown'])
        with self.assertRaises(attempts.AttemptNotFound):
            attempts.by_request(self.root, 'd' * 32, BODY['request_id'])
        self.assertEqual(attempts.list_for_take(self.root, 'd' * 32), [])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        attempts.run(self.root, record['attempt_id'], refine=refine, submit=submit)
        refine.assert_not_called()
        submit.assert_not_called()


class RootHttpTests(RootFixture):
    def client(self, *, worker=None, precheck=None):
        app = FastAPI()
        app.include_router(api.create_router(lambda: self.work, lambda: self.root,
            worker=worker, precheck=precheck))
        app.include_router(attempt_router(lambda: self.root))
        return TestClient(app)

    def upload(self, client, payload=None, mime='image/png'):
        return client.post('/api/continuity/root-references', files={
            'image': ('../../UNTRUSTED.jpg', payload if payload is not None else image_bytes(), mime)})

    def request_body(self, client):
        ids = [self.upload(client, image_bytes(c)).json()['reference_id'] for c in ('red', 'blue')]
        return BODY | {'reference_ids': ids, 'width': 960, 'height': 544}

    def test_http_upload_is_immutable_png_ids_only_and_metadata_is_removed(self):
        with self.client() as client:
            first = self.upload(client, image_bytes(metadata=True))
            self.assertEqual(first.status_code, 201, first.text)
            self.assertEqual(set(first.json()), {'reference_id', 'url'})
            self.assertRegex(first.json()['reference_id'], r'^[0-9a-f]{32}$')
            downloaded = client.get(first.json()['url'])
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(downloaded.headers['content-type'], 'image/png')
            with Image.open(BytesIO(downloaded.content)) as image:
                self.assertNotIn('prompt', image.info)
            second = self.upload(client, image_bytes('blue', format='JPEG'), 'image/jpeg')
            self.assertEqual(second.status_code, 201, second.text)
            self.assertNotEqual(first.json()['reference_id'], second.json()['reference_id'])
            self.assertEqual(client.get(first.json()['url']).content, downloaded.content)
            path = self.work / 'media' / ('root-reference-' + first.json()['reference_id'] + '.png')
            self.assertEqual(path.stat().st_mode & 0o222, 0)
            self.assertEqual(len(list((self.work / 'media').iterdir())), 2)
            self.assertEqual(client.put(first.json()['url'], content=b'changed').status_code, 405)

    def test_http_bad_upload_mime_sniff_size_bombs_and_symlinks_cost_no_worker(self):
        worker, precheck = Mock(), Mock()
        with self.client(worker=worker, precheck=precheck) as client:
            for payload, mime in [(b'not an image', 'image/png'), (image_bytes(), 'image/jpeg'),
                                  (image_bytes(), 'text/plain'), (b'', 'image/png')]:
                response = self.upload(client, payload, mime)
                self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(self.upload(client, b'x' * (MAX_REFERENCE_BYTES + 1)).status_code, 413)
            with patch.object(Image, 'MAX_IMAGE_PIXELS', 100):
                self.assertEqual(self.upload(client).status_code, 422)
            self.assertFalse(self.work.exists())
            outside = Path(self.tmp.name) / 'outside'
            outside.mkdir()
            self.work.mkdir()
            (self.work / 'media').symlink_to(outside, target_is_directory=True)
            self.assertEqual(self.upload(client).status_code, 503)
            self.assertEqual(list(outside.iterdir()), [])
        worker.start.assert_not_called()
        precheck.assert_not_called()

    def test_http_strict_invalid_and_missing_inputs_are_before_worker_or_precheck(self):
        worker, precheck = Mock(), Mock()
        with self.client(worker=worker, precheck=precheck) as client:
            body = self.request_body(client)
            changes = [{'mode': 'root'}, {'root_context': CONTEXT}, {'take_id': None},
                       {'second_take_id': 'e' * 32}, {'reference_ids': []},
                       {'reference_ids': ['A' * 32]}, {'reference_ids': ['a' * 32 + '\n']},
                       {'reference_ids': ['../bad']}, {'width': 2080}, {'height': 33},
                       {'width': True}, {'width': 960.0}, {'height': '544'},
                       {'prompt': ' '}, {'prompt': 'x' * 4001}, {'raw_frames': 193},
                       {'raw_frames': True}, {'seeds': [True]}, {'seeds': [2 ** 64]},
                       {'seeds': [-1]}, {'seeds': [1, 1]}, {'seeds': []}, {'seeds': [1, 2, 3, 4, 5]}]
            for variant in [body | change for change in changes] + [
                    {k: v for k, v in body.items() if k != key} for key in body]:
                with self.subTest(variant=variant):
                    response = client.post('/api/continuity/roots/attempts', json=variant)
                    self.assertEqual(response.status_code, 422, response.text)
            # Valid JSON but unknown image or too-short root also refuses early.
            for change in ({'reference_ids': ['f' * 32]}, {'raw_frames': 22}):
                self.assertEqual(client.post('/api/continuity/roots/attempts', json=body | change).status_code, 422)
        self.assertFalse(self.root.exists())
        worker.start.assert_not_called()
        precheck.assert_not_called()

    def test_http_precheck_refusal_precedes_record_and_filters_private_error(self):
        worker = Mock()
        precheck = Mock(side_effect=ValueError('/private/SECRET prepared prompt'))
        with self.client(worker=worker, precheck=precheck) as client:
            body = self.request_body(client)
            response = client.post('/api/continuity/roots/attempts', json=body)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('SECRET', response.text)
        precheck.assert_called_once_with({
            'reference_ids': body['reference_ids'], 'width': 960, 'height': 544}, 192, BODY['prompt'])
        self.assertFalse(self.root.exists())
        worker.start.assert_not_called()

    def test_http_idempotency_conflict_root_scoped_get_and_generic_shared_status(self):
        worker, precheck = Mock(), Mock()
        with self.client(worker=worker, precheck=precheck) as client:
            body = self.request_body(client)
            first = client.post('/api/continuity/roots/attempts', json=body)
            self.assertEqual(first.status_code, 202, first.text)
            self.assertEqual(first.json()['mode'], 'root')
            self.assertIsNone(first.json()['take_id'])
            self.assertEqual(client.post('/api/continuity/roots/attempts', json=body).json(), first.json())
            self.assertEqual(client.post('/api/continuity/roots/attempts', json=body | {
                'reference_ids': list(reversed(body['reference_ids']))}).status_code, 409)
            before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            url = '/api/continuity/roots/attempts/by-request/' + BODY['request_id']
            self.assertEqual(client.get(url).json(), first.json())
            self.assertEqual(client.get('/api/continuity/attempts/' + first.json()['attempt_id']).json(), first.json())
            self.assertEqual(client.get('/api/continuity/takes/' + 'd' * 32 + '/attempts/by-request/' + BODY['request_id']).status_code, 404)
            forward = attempts.create(self.root, take_id='d' * 32, **(BODY | {'request_id': 'e' * 32}))
            self.assertEqual(client.get('/api/continuity/roots/attempts/by-request/' + 'e' * 32).status_code, 404)
            # No POST after this snapshot: recovery is strictly read-only.
            before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            self.assertEqual(client.get(url).status_code, 200)
            self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        worker.start.assert_called_once_with(first.json()['attempt_id'])


if __name__ == '__main__':
    unittest.main()
