"""CPU-only native intent, HTTP validation and durable anchored hunt recovery."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, call

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_attempts as attempts  # noqa: E402
from continuity_attempt_api import create_router  # noqa: E402

TAKE = 'a' * 32
SECOND = 'c' * 32
BODY = {'request_id': 'b' * 32, 'prompt': 'Continue the motion',
        'raw_frames': 158, 'seeds': [0, 2 ** 64 - 1]}
PUBLIC_KEYS = {'attempt_id', 'take_id', 'status', 'error', 'candidates'}


class AnchoredAttemptsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def make(self, **changes):
        return attempts.create(self.root, take_id=TAKE, **(BODY | changes))

    def client(self, **kwargs):
        app = FastAPI()
        app.include_router(create_router(lambda: self.root, **kwargs))
        return TestClient(app)

    @property
    def url(self):
        return f'/api/continuity/takes/{TAKE}/attempts'

    def test_nonforward_intent_is_durable_and_public_but_forward_shape_is_exact(self):
        for mode, second in [('forward', None), ('prepend', None), ('bridge', SECOND)]:
            with self.subTest(mode=mode):
                record = self.make(request_id=None, mode=mode, second_take_id=second)
                saved = attempts.load(self.root, record['attempt_id'])
                self.assertEqual(saved, record)
                view = attempts.public(saved)
                if mode == 'forward':
                    self.assertEqual(set(view), PUBLIC_KEYS)
                    self.assertNotIn('mode', record)
                    self.assertNotIn('second_take_id', record)
                else:
                    self.assertEqual(set(view), PUBLIC_KEYS | {'mode', 'second_take_id'})
                    self.assertEqual((saved['mode'], saved['second_take_id']), (mode, second))
                    self.assertEqual((view['mode'], view['second_take_id']), (mode, second))

    def test_internal_validation_refuses_before_any_store_write(self):
        for changes in ({'mode': 'root'}, {'mode': None}, {'mode': []},
                        {'mode': 'bridge'}, {'mode': 'bridge', 'second_take_id': TAKE},
                        {'mode': 'bridge', 'second_take_id': SECOND.upper()},
                        {'mode': 'bridge', 'second_take_id': SECOND + '\n'},
                        {'mode': 'bridge', 'second_take_id': 4},
                        {'mode': 'forward', 'second_take_id': SECOND},
                        {'mode': 'prepend', 'second_take_id': SECOND}):
            with self.subTest(changes=changes), self.assertRaises(attempts.AttemptError):
                self.make(**changes)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_legacy_default_and_explicit_forward_are_idempotent(self):
        legacy = self.make()
        self.assertNotIn('mode', legacy)
        self.assertEqual(self.make(mode='forward', second_take_id=None), legacy)
        with self.assertRaises(attempts.AttemptConflict):
            self.make(mode='prepend')
        with self.assertRaises(attempts.AttemptConflict):
            self.make(mode='bridge', second_take_id=SECOND)

    def test_idempotency_freezes_both_mode_and_second_parent(self):
        original = self.make(mode='bridge', second_take_id=SECOND)
        self.assertEqual(self.make(mode='bridge', second_take_id=SECOND), original)
        for changes in ({'mode': 'prepend'}, {'mode': 'forward'},
                        {'mode': 'bridge', 'second_take_id': 'd' * 32}):
            with self.subTest(changes=changes), self.assertRaises(attempts.AttemptConflict):
                self.make(**changes)
        self.assertEqual(len(list(self.root.rglob('attempt.json'))), 1)

    def test_nonforward_callbacks_have_exact_keywords_refine_once_and_do_not_resubmit(self):
        for mode, second in [('prepend', None), ('bridge', SECOND)]:
            with self.subTest(mode=mode):
                record = self.make(request_id=None, mode=mode, second_take_id=second)
                refine = Mock(return_value='frozen model prompt')
                submit = Mock(side_effect=['d' * 32, 'e' * 32])
                result = attempts.run(self.root, record['attempt_id'], refine=refine, submit=submit)
                self.assertEqual(result['status'], 'done')
                refine.assert_called_once_with(BODY['prompt'], TAKE, mode=mode, second_take_id=second)
                self.assertEqual(submit.call_args_list, [
                    call(c['operation_id'], 'frozen model prompt', c['seed'], 158, TAKE,
                         mode=mode, second_take_id=second) for c in record['candidates']])
                self.assertEqual(attempts.run(self.root, record['attempt_id'],
                                             refine=refine, submit=submit), result)
                self.assertEqual(refine.call_count, 1)
                self.assertEqual(submit.call_count, 2)

    def test_forward_callbacks_remain_positional_without_new_kwargs(self):
        record = self.make(mode='forward')
        refine, submit = Mock(return_value='frozen'), Mock(return_value='d' * 32)
        result = attempts.run(self.root, record['attempt_id'], refine=refine, submit=submit)
        self.assertEqual(result['status'], 'done')
        refine.assert_called_once_with(BODY['prompt'], TAKE)
        self.assertEqual(submit.call_args_list, [
            call(c['operation_id'], 'frozen', c['seed'], 158, TAKE) for c in record['candidates']])

    def test_partial_retry_retains_two_parent_intent_and_saved_refinement(self):
        record = self.make(mode='bridge', second_take_id=SECOND)
        refine = Mock(return_value='frozen')
        first_submit = Mock(side_effect=['d' * 32, ValueError('refused')])
        attempts.run(self.root, record['attempt_id'], refine=refine, submit=first_submit)
        submit = Mock(return_value='e' * 32)
        result = attempts.run(self.root, record['attempt_id'], refine=refine, submit=submit)
        self.assertEqual(result['status'], 'done')
        self.assertEqual(refine.call_count, 1)
        submit.assert_called_once_with(record['candidates'][1]['operation_id'], 'frozen',
                                       2 ** 64 - 1, 158, TAKE, mode='bridge', second_take_id=SECOND)

    def test_worker_serializes_and_deduplicates_two_parent_callbacks(self):
        record = self.make(mode='bridge', second_take_id=SECOND)
        entered, release = threading.Event(), threading.Event()

        def refine(prompt, take_id, *, mode, second_take_id):
            self.assertEqual((prompt, take_id, mode, second_take_id),
                             (BODY['prompt'], TAKE, 'bridge', SECOND))
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test release timeout')
            return 'frozen'

        refiner, submit = Mock(side_effect=refine), Mock(return_value='d' * 32)
        worker = attempts.Worker(self.root, refine=refiner, submit=submit)
        worker.start(record['attempt_id'])
        thread = worker._thread
        try:
            self.assertTrue(entered.wait(5))
            worker.start(record['attempt_id'])
            self.assertEqual(worker.reconcile(), [])
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(attempts.load(self.root, record['attempt_id'])['status'], 'done')
        self.assertEqual(refiner.call_count, 1)
        self.assertEqual(submit.call_count, 2)
        for submitted in submit.call_args_list:
            self.assertEqual(submitted.kwargs, {'mode': 'bridge', 'second_take_id': SECOND})

    def test_http_modes_exact_forward_hooks_and_anchored_precheck(self):
        worker, legacy, anchored = Mock(), Mock(), Mock()
        with self.client(worker=worker, precheck=legacy, anchored_precheck=anchored) as client:
            for index, (mode, second) in enumerate([('forward', None), ('prepend', None),
                                                  ('bridge', SECOND)]):
                body = BODY | {'request_id': f'{index:032x}', 'mode': mode}
                if second is not None:
                    body['second_take_id'] = second
                response = client.post(self.url, json=body)
                self.assertEqual(response.status_code, 202, response.text)
                if mode == 'forward':
                    self.assertEqual(set(response.json()), PUBLIC_KEYS)
                else:
                    self.assertEqual(response.json()['mode'], mode)
                    self.assertEqual(response.json()['second_take_id'], second)
        legacy.assert_called_once_with(TAKE, 158)
        self.assertEqual(anchored.call_args_list, [
            call(TAKE, 158, mode='prepend', second_take_id=None),
            call(TAKE, 158, mode='bridge', second_take_id=SECOND)])
        self.assertEqual(worker.start.call_count, 3)

    def test_http_malformed_modes_ids_and_seeds_never_create_precheck_or_start(self):
        worker, create, legacy, anchored = Mock(), Mock(), Mock(), Mock()
        invalid = [{'mode': mode} for mode in ['root', 'before', 'FORWARD', '', None, True, 3, []]]
        invalid += [{'mode': 'bridge'}, {'mode': 'bridge', 'second_take_id': None}]
        invalid += [{'mode': 'bridge', 'second_take_id': value} for value in
                    [TAKE, SECOND.upper(), SECOND[:-1], SECOND + '\n', 1, True, [], '']]
        invalid += [{'mode': mode, 'second_take_id': SECOND} for mode in ['forward', 'prepend']]
        invalid += [{'mode': 'bridge', 'second_take_id': SECOND, 'seeds': seeds} for seeds in
                    [[0, 0], [True], [2 ** 64], [-1], ['1'], [], [1, 2, 3, 4, 5]]]
        with self.client(worker=worker, create=create, precheck=legacy,
                         anchored_precheck=anchored) as client:
            for changes in invalid:
                with self.subTest(changes=changes):
                    response = client.post(self.url, json=BODY | changes)
                    self.assertEqual(response.status_code, 422, response.text)
        create.assert_not_called()
        worker.start.assert_not_called()
        legacy.assert_not_called()
        anchored.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_http_anchor_refusal_is_before_creation(self):
        worker, create = Mock(), Mock()
        anchored = Mock(side_effect=ValueError('Both anchors must be continuable.'))
        with self.client(worker=worker, create=create, anchored_precheck=anchored) as client:
            response = client.post(self.url, json=BODY | {'mode': 'bridge', 'second_take_id': SECOND})
        self.assertEqual(response.status_code, 422)
        create.assert_not_called()
        worker.start.assert_not_called()

    def test_forward_creation_hook_does_not_receive_new_keywords(self):
        record = self.make()
        create, worker = Mock(return_value=(record, False)), Mock()
        with self.client(worker=worker, create=create) as client:
            self.assertEqual(client.post(self.url, json=BODY | {'mode': 'forward'}).status_code, 202)
        create.assert_called_once_with(self.root, take_id=TAKE, **BODY)
        worker.start.assert_not_called()

    def test_http_idempotency_mode_conflicts_and_take_scoped_read_only_recovery(self):
        worker = Mock()
        body = BODY | {'mode': 'bridge', 'second_take_id': SECOND}
        with self.client(worker=worker) as client:
            first = client.post(self.url, json=body)
            self.assertEqual(first.status_code, 202, first.text)
            self.assertEqual(client.post(self.url, json=body).json(), first.json())
            for changes in ({'mode': 'prepend', 'second_take_id': None},
                            {'mode': 'forward', 'second_take_id': None},
                            {'second_take_id': 'd' * 32}):
                self.assertEqual(client.post(self.url, json=body | changes).status_code, 409)
            before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            self.assertEqual(client.get(self.url + '/by-request/' + BODY['request_id']).json(), first.json())
            self.assertEqual(client.get(self.url).json()['attempts'], [first.json()])
            self.assertEqual(client.get('/api/continuity/attempts/' + first.json()['attempt_id']).json(),
                             first.json())
            wrong = f'/api/continuity/takes/{SECOND}/attempts'
            self.assertEqual(client.get(wrong + '/by-request/' + BODY['request_id']).status_code, 404)
            self.assertEqual(client.get(wrong).json()['attempts'], [])
            self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        worker.start.assert_called_once_with(first.json()['attempt_id'])

    def test_fresh_worker_startup_reconciles_modes_without_requeue_or_compute(self):
        for mode, second in [('prepend', None), ('bridge', SECOND)]:
            with self.subTest(mode=mode):
                request_id = ('1' if mode == 'prepend' else '2') * 32
                body = BODY | {'request_id': request_id, 'mode': mode, 'second_take_id': second}
                record = self.make(mode=mode, second_take_id=second, request_id=request_id)
                record.update(status='running', refined_prompt='frozen')
                record['candidates'][0].update(status='done', take_id='d' * 32)
                record['candidates'][1].update(status='running')
                attempts._atomic(attempts._folder(self.root, record['attempt_id']) / 'attempt.json', record)
                refine, submit = Mock(), Mock()
                worker = attempts.Worker(self.root, refine=refine, submit=submit)
                with self.client(worker=worker) as client:
                    recovered = client.get('/api/continuity/attempts/' + record['attempt_id']).json()
                    self.assertEqual(recovered['mode'], mode)
                    self.assertEqual(recovered['second_take_id'], second)
                    self.assertEqual([c['status'] for c in recovered['candidates']], ['done', 'unknown'])
                    self.assertEqual(client.post(self.url, json=body).json(), recovered)
                    self.assertEqual(attempts.run(self.root, record['attempt_id'],
                                                 refine=refine, submit=submit)['mode'], mode)
                refine.assert_not_called()
                submit.assert_not_called()
                self.assertIsNone(worker._thread)

    def test_reconciliation_preserves_pending_and_fully_completed_anchored_intent(self):
        for mode, second in [('prepend', None), ('bridge', SECOND)]:
            for phase in ['pending', 'completed']:
                with self.subTest(mode=mode, phase=phase):
                    record = self.make(mode=mode, second_take_id=second, request_id=None)
                    if phase == 'completed':
                        record.update(status='running', refined_prompt='frozen')
                        for candidate in record['candidates']:
                            candidate.update(status='done', take_id='d' * 32)
                        attempts._atomic(attempts._folder(self.root, record['attempt_id']) / 'attempt.json',
                                         record)
                    self.assertEqual(attempts.reconcile_interrupted(self.root), [record['attempt_id']])
                    saved = attempts.load(self.root, record['attempt_id'])
                    self.assertEqual((saved['mode'], saved['second_take_id']), (mode, second))
                    self.assertEqual(saved['status'], 'done' if phase == 'completed' else 'failed')
                    self.assertEqual([c['status'] for c in saved['candidates']],
                                     ['done' if phase == 'completed' else 'failed'] * 2)

    def test_invalid_persisted_intent_cannot_fall_back_to_forward_compute(self):
        record = self.make(mode='bridge', second_take_id=SECOND)
        path = attempts._folder(self.root, record['attempt_id']) / 'attempt.json'
        refine, submit = Mock(), Mock()
        for changes in [{'mode': 'root'}, {'mode': None}, {'second_take_id': None},
                        {'second_take_id': TAKE}, {'second_take_id': SECOND.upper()}]:
            with self.subTest(changes=changes):
                attempts._atomic(path, record | changes)
                with self.assertRaises(attempts.AttemptError):
                    attempts.run(self.root, record['attempt_id'], refine=refine, submit=submit)
        refine.assert_not_called()
        submit.assert_not_called()

    def test_nonforward_public_errors_stay_filtered_after_reload(self):
        record = self.make(mode='bridge', second_take_id=SECOND)
        record['error'] = 'PRIVATE_TOKEN /private/secret prompt'
        record['candidates'][0]['error'] = record['error']
        attempts._atomic(attempts._folder(self.root, record['attempt_id']) / 'attempt.json', record)
        view = attempts.public(attempts.load(self.root, record['attempt_id']))
        self.assertNotIn('PRIVATE_TOKEN', json.dumps(view))
        self.assertNotIn('/private/', json.dumps(view))
        self.assertEqual(view['second_take_id'], SECOND)


if __name__ == '__main__':
    unittest.main()
