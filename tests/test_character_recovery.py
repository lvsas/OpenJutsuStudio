"""A restart closes the character jobs it interrupted, and touches nothing else."""
import json
import tempfile
import unittest
from pathlib import Path

from character_recovery import fail_interrupted


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / 'jobs').mkdir()

    def write(self, job_id, **record):
        path = self.root / 'jobs' / f'{job_id}.json'
        path.write_text(json.dumps(record))
        return path

    def test_a_running_character_job_is_closed_with_an_actionable_message(self):
        self.write('a' * 32, engine='flux3-klein-character', status='running', meta={})
        self.assertEqual(fail_interrupted(self.root), ['a' * 32])
        record = json.loads((self.root / 'jobs' / f'{"a" * 32}.json').read_text())
        self.assertEqual(record['status'], 'error')
        self.assertIn('Run it again', record['error'])

    def test_finished_and_foreign_jobs_are_untouched(self):
        self.write('b' * 32, engine='flux3-klein-character', status='done', meta={})
        self.write('c' * 32, engine='ltx-ripple', status='running', meta={})
        self.assertEqual(fail_interrupted(self.root), [])
        self.assertEqual(json.loads((self.root / 'jobs' / f'{"c" * 32}.json').read_text())['status'], 'running')

    def test_a_second_start_finds_nothing_left_to_close(self):
        self.write('d' * 32, engine='flux3-klein-character', status='queued', meta={})
        fail_interrupted(self.root)
        self.assertEqual(fail_interrupted(self.root), [])


if __name__ == '__main__':
    unittest.main()
