"""A hunt freezes one direction, varies only seeds, and never erases a candidate."""
import sys
from pathlib import Path
import tempfile
import os
import unittest

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
