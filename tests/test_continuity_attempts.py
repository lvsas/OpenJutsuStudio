"""A hunt freezes one direction, varies only seeds, and never erases a candidate."""
import sys
from pathlib import Path
import tempfile
import os
import unittest
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch


def create_in_process(root):
    import continuity_attempts
    return continuity_attempts.create(root, take_id='a' * 32, request_id='b' * 32,
                                     prompt='Keep the motion', raw_frames=158,
                                     seeds=[7, 8])['attempt_id']


def crash_in_process(root, attempt_id):
    import continuity_attempts

    def submit(operation_id, refined, seed, *args):
        if seed == 2:
            os._exit(17)  # Real process death after the durable running checkpoint.
        return 'c' * 32

    continuity_attempts.run(root, attempt_id, refine=lambda *args: 'frozen', submit=submit)


def crash_in_refine_process(root, attempt_id):
    import continuity_attempts

    def refine(*args):
        os._exit(19)  # Real death while the durable record is still pending.

    continuity_attempts.run(root, attempt_id, refine=refine,
                            submit=lambda *args: 'c' * 32)


def run_in_process(root, attempt_id, entered, release):
    import continuity_attempts

    def refine(*args):
        entered.set()
        if not release.wait(10):
            raise RuntimeError('test release timed out')
        return 'frozen'

    continuity_attempts.run(root, attempt_id, refine=refine, submit=lambda *args: 'c' * 32)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_attempts as attempts  # noqa: E402

TAKE = 'a' * 32


class AttemptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def make(self, seeds=(7, 8, 9)):
        return attempts.create(self.root, take_id=TAKE, prompt='Keep the motion',
                               raw_frames=158, seeds=seeds)

    def test_seeds_are_the_only_variable_and_must_be_distinct(self):
        with self.assertRaisesRegex(attempts.AttemptError, 'distinct'):
            self.make((7, 7))
        with self.assertRaisesRegex(attempts.AttemptError, 'distinct'):
            self.make((1, 2, 1))
        with self.assertRaisesRegex(attempts.AttemptError, 'between 1 and'):
            self.make(())

    def test_a_seed_above_the_uint64_range_is_refused(self):
        with self.assertRaisesRegex(attempts.AttemptError, 'distinct'):
            self.make((2 ** 64,))

    def test_the_direction_is_refined_once_for_the_whole_hunt(self):
        attempt = self.make()
        calls = []

        def refine(prompt, take_id):
            calls.append(prompt)
            return 'subject_definitions: <Subject 1>…'

        def submit(operation_id, refined, seed, frames, take_id):
            self.assertEqual(refined, 'subject_definitions: <Subject 1>…')
            return ('c' if seed == 7 else 'd' if seed == 8 else 'e') * 32

        result = attempts.run(self.root, attempt['attempt_id'], refine=refine, submit=submit)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['status'], 'done')
        self.assertEqual([c['status'] for c in result['candidates']], ['done'] * 3)
        self.assertEqual([c['take_id'] for c in result['candidates']],
                         ['c' * 32, 'd' * 32, 'e' * 32])

    def test_a_failed_candidate_keeps_the_others_and_the_hunt_still_counts_as_done(self):
        attempt = self.make((1, 2))

        def submit(operation_id, refined, seed, frames, take_id):
            if seed == 2:
                raise ValueError('The GPU refused this one.')
            return 'f' * 32

        result = attempts.run(self.root, attempt['attempt_id'],
                              refine=lambda prompt, take_id: 'ok', submit=submit)
        self.assertEqual(result['status'], 'done')
        self.assertEqual([c['status'] for c in result['candidates']], ['done', 'failed'])
        self.assertIn('GPU refused', result['candidates'][1]['error'])

    def test_a_failed_refiner_stops_before_any_submission(self):
        attempt = self.make()
        submitted = []
        result = attempts.run(self.root, attempt['attempt_id'],
                              refine=lambda prompt, take_id: (_ for _ in ()).throw(ValueError('no prompt')),
                              submit=lambda *a: submitted.append(a) or 'x' * 32)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(submitted, [])
        self.assertIn('could not be prepared', result['error'])

    def test_a_resumed_hunt_retries_only_the_candidate_that_failed(self):
        attempt = self.make((1, 2))
        seen, failed_once = [], set()

        def submit(operation_id, refined, seed, frames, take_id):
            seen.append(seed)
            if seed == 1 and seed not in failed_once:
                failed_once.add(seed)
                raise ValueError('first attempt died')
            return 'a' * 32

        attempts.run(self.root, attempt['attempt_id'],
                     refine=lambda prompt, take_id: 'ok', submit=submit)
        seen.clear()
        attempts.run(self.root, attempt['attempt_id'],
                     refine=lambda prompt, take_id: 'ok', submit=submit)
        self.assertEqual(seen, [1], 'the completed candidate must not run again')
        self.assertEqual([c['status'] for c in attempts.load(self.root, attempt['attempt_id'])['candidates']],
                         ['done', 'done'])

    def test_request_identity_is_frozen_and_validated(self):
        kwargs = dict(take_id=TAKE, request_id='b' * 32, prompt='Keep the motion',
                      raw_frames=158, seeds=[7, 8])
        first = attempts.create(self.root, **kwargs)
        self.assertEqual(first['request_id'], kwargs['request_id'])
        self.assertEqual(attempts.create(self.root, **kwargs), first)
        for change in ({'prompt': 'Other'}, {'raw_frames': 175}, {'seeds': [8, 7]},
                       {'take_id': 'c' * 32}):
            with self.subTest(change=change), self.assertRaises(attempts.AttemptConflict):
                attempts.create(self.root, **(kwargs | change))
        with self.assertRaises(attempts.AttemptError):
            attempts.create(self.root, **(kwargs | {'request_id': 'B' * 32}))
        self.assertEqual(len(list(self.root.rglob('attempt.json'))), 1)

    def test_concurrent_threads_create_only_one_record(self):
        barrier = threading.Barrier(8)

        def create(_):
            barrier.wait(timeout=5)
            return create_in_process(self.root)

        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(create, range(8)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(list(self.root.rglob('attempt.json'))), 1)

    def test_concurrent_processes_create_only_one_record(self):
        with multiprocessing.get_context('spawn').Pool(4) as pool:
            ids = pool.map(create_in_process, [str(self.root)] * 12)
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(list(self.root.rglob('attempt.json'))), 1)

    def test_lookup_and_listing_do_not_write_or_create_records(self):
        empty = self.root / 'absent'
        with self.assertRaises(attempts.AttemptError):
            attempts.by_request(empty, TAKE, 'b' * 32)
        self.assertEqual(attempts.list_for_take(empty, TAKE), [])
        self.assertFalse(empty.exists())
        legacy = self.make()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(attempts.list_for_take(self.root, TAKE), [legacy])
        with self.assertRaises(attempts.AttemptError):
            attempts.by_request(self.root, TAKE, 'b' * 32)
        after = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_rerunning_completed_attempt_does_not_refine_or_submit(self):
        attempt = self.make((1,))
        first = attempts.run(self.root, attempt['attempt_id'],
                             refine=lambda *a: 'frozen', submit=lambda *a: 'c' * 32)
        refine, submit = Mock(side_effect=AssertionError), Mock(side_effect=AssertionError)
        self.assertEqual(attempts.run(self.root, attempt['attempt_id'],
                                     refine=refine, submit=submit), first)
        refine.assert_not_called()
        submit.assert_not_called()

    def test_partial_retry_reuses_saved_refinement(self):
        attempt = self.make((1, 2))

        def submit(operation_id, refined, seed, *args):
            if seed == 2:
                raise ValueError('failed')
            return 'c' * 32

        attempts.run(self.root, attempt['attempt_id'], refine=lambda *a: 'frozen', submit=submit)
        refine, submit = Mock(side_effect=AssertionError), Mock(return_value='d' * 32)
        result = attempts.run(self.root, attempt['attempt_id'], refine=refine, submit=submit)
        refine.assert_not_called()
        self.assertEqual(result['refined_prompt'], 'frozen')
        submit.assert_called_once_with(attempt['candidates'][1]['operation_id'],
                                       'frozen', 2, 158, TAKE)

    def test_crashed_running_candidate_is_blocked_not_blindly_resubmitted(self):
        attempt = self.make((1, 2))
        attempt['refined_prompt'] = 'frozen'
        attempt['status'] = 'running'
        attempt['candidates'][0]['status'] = 'running'
        attempts._atomic(attempts._folder(self.root, attempt['attempt_id']) / 'attempt.json', attempt)
        refine, submit = Mock(), Mock()
        result = attempts.run(self.root, attempt['attempt_id'], refine=refine, submit=submit)
        again = attempts.run(self.root, attempt['attempt_id'], refine=refine, submit=submit)
        self.assertEqual(result, again)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['candidates'][0]['status'], 'unknown')
        self.assertIn('unknown', result['error'])
        refine.assert_not_called()
        submit.assert_not_called()

    def test_real_process_crash_preserves_done_and_blocks_interrupted_candidate(self):
        attempt = self.make((1, 2))
        process = multiprocessing.get_context('spawn').Process(
            target=crash_in_process, args=(str(self.root), attempt['attempt_id']))
        process.start()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join()
            self.fail('Crash test child did not exit')
        self.assertEqual(process.exitcode, 17)
        saved = attempts.load(self.root, attempt['attempt_id'])
        self.assertEqual(saved['refined_prompt'], 'frozen')
        self.assertEqual([c['status'] for c in saved['candidates']], ['done', 'running'])
        refine, submit = Mock(), Mock()
        result = attempts.run(self.root, attempt['attempt_id'], refine=refine, submit=submit)
        self.assertEqual([c['status'] for c in result['candidates']], ['done', 'unknown'])
        self.assertEqual(result['candidates'][0]['take_id'], 'c' * 32)
        refine.assert_not_called()
        submit.assert_not_called()

    def test_a_second_process_cannot_run_the_same_attempt(self):
        attempt = self.make((1,))
        context = multiprocessing.get_context('spawn')
        entered, release = context.Event(), context.Event()
        process = context.Process(target=run_in_process,
                                  args=(str(self.root), attempt['attempt_id'], entered, release))
        process.start()
        try:
            self.assertTrue(entered.wait(10))
            self.assertEqual(attempts.reconcile_interrupted(self.root), [],
                             'an active refiner owns the pending record run lock')
            self.assertEqual(attempts.load(self.root, attempt['attempt_id'])['status'], 'pending')
            refine, submit = Mock(), Mock()
            attempts.run(self.root, attempt['attempt_id'], refine=refine, submit=submit)
            refine.assert_not_called()
            submit.assert_not_called()
        finally:
            release.set()
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join()
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(attempts.load(self.root, attempt['attempt_id'])['status'], 'done')

    def test_startup_reconciliation_does_not_touch_a_live_executor_lock(self):
        record = self.make((1,))
        record['status'] = 'running'
        record['refined_prompt'] = 'frozen'
        record['candidates'][0]['status'] = 'running'
        folder = attempts._folder(self.root, record['attempt_id'])
        attempts._atomic(folder / 'attempt.json', record)
        before = (folder / 'attempt.json').read_bytes()
        with attempts._file_lock(folder / '.run.lock'):
            self.assertEqual(attempts.reconcile_interrupted(self.root), [])
            self.assertEqual((folder / 'attempt.json').read_bytes(), before)
        self.assertEqual(attempts.reconcile_interrupted(self.root), [record['attempt_id']])
        self.assertEqual(attempts.load(self.root, record['attempt_id'])['candidates'][0]['status'], 'unknown')
        self.assertEqual(attempts.reconcile_interrupted(self.root), [], 'reconciliation is idempotent')
        absent = self.root / 'absent'
        self.assertEqual(attempts.reconcile_interrupted(absent), [])
        self.assertFalse(absent.exists())

    def test_startup_finalizes_an_already_completed_candidate_summary(self):
        record = self.make((1,))
        record['status'] = 'running'
        record['refined_prompt'] = 'frozen'
        record['candidates'][0].update(status='done', take_id='c' * 32)
        attempts._atomic(attempts._folder(self.root, record['attempt_id']) / 'attempt.json', record)
        self.assertEqual(attempts.reconcile_interrupted(self.root), [record['attempt_id']])
        saved = attempts.load(self.root, record['attempt_id'])
        self.assertEqual(saved['status'], 'done')
        self.assertIsNone(saved['error'])
        self.assertEqual(saved['refined_prompt'], 'frozen')
        self.assertEqual(saved['candidates'], record['candidates'])

    def test_worker_deduplicates_while_run_is_active(self):
        attempt = self.make((1,))
        entered, release = threading.Event(), threading.Event()

        def refine(*args):
            entered.set()
            if not release.wait(10):
                raise RuntimeError('test release timed out')
            return 'frozen'

        worker = attempts.Worker(self.root, refine=refine, submit=lambda *a: 'c' * 32)
        with patch.object(attempts, 'run', wraps=attempts.run) as run:
            worker.start(attempt['attempt_id'])
            thread = worker._thread
            try:
                self.assertTrue(entered.wait(5))
                worker.start(attempt['attempt_id'])
            finally:
                release.set()
                thread.join(10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(run.call_count, 1)

    def test_unknown_and_malformed_attempts_are_refused(self):
        with self.assertRaisesRegex(attempts.AttemptError, 'not found'):
            attempts.load(self.root, 'b' * 32)
        with self.assertRaisesRegex(attempts.AttemptError, 'identifier'):
            attempts.load(self.root, '../escape')

    def test_the_public_view_never_leaks_internal_paths(self):
        attempt = self.make((5,))
        view = attempts.public(attempt)
        self.assertNotIn(str(self.root), str(view))
        self.assertEqual(set(view), {'attempt_id', 'take_id', 'status', 'error', 'candidates'})


if __name__ == '__main__':
    unittest.main()
