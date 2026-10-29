"""Permanent Swap deletion: lineage guard, media ownership and refusals."""
from pathlib import Path
import json
import os
import tempfile
import unittest

from job_delete import JobDeletionRefused, delete_job

JOB = 'a' * 32
LIVE = 'b' * 32


class JobFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        (self.work / 'jobs').mkdir()
        (self.work / 'media').mkdir()
        (self.work / 'timeline' / 'continuable-takes').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, job_id=JOB, status='done'):
        (self.work / 'jobs' / (job_id + '.json')).write_text(json.dumps({'id': job_id, 'status': status}))
        media = self.work / 'media'
        (media / (job_id + '-source.mp4')).write_bytes(b's' * 100)
        (media / (job_id + '-reference-1.png')).write_bytes(b'r' * 50)
        result = media / ('h3-' + job_id)
        result.mkdir()
        (result / 'result.mp4').write_bytes(b'v' * 200)
        return media

    def take_using(self, job_id=JOB, take_id='c' * 32):
        directory = self.work / 'timeline' / 'continuable-takes' / take_id
        directory.mkdir()
        (directory / 'capsule.json').write_text(json.dumps({'origin': {'source_job': job_id}}))


class JobDeletionRules(JobFixture):
    def test_job_record_and_every_owned_media_file_are_removed(self):
        self.job()
        result = delete_job(self.work, JOB)
        self.assertEqual(result['deleted'], JOB)
        self.assertGreaterEqual(result['bytes'], 350)
        media = self.work / 'media'
        self.assertFalse((self.work / 'jobs' / (JOB + '.json')).exists())
        self.assertEqual(sorted(p.name for p in media.iterdir()), [])

    def test_unknown_malformed_or_traversal_identifiers_are_refused(self):
        for value in ('f' * 32, '../jobs', JOB.upper(), ''):
            with self.subTest(value=value):
                with self.assertRaises(JobDeletionRefused):
                    delete_job(self.work, value)

    def test_running_job_is_refused(self):
        self.job(LIVE)
        for status in ('running', 'queued', 'submitting', 'propagating'):
            with self.subTest(status=status):
                (self.work / 'jobs' / (LIVE + '.json')).write_text(json.dumps({'id': LIVE, 'status': status}))
                with self.assertRaises(JobDeletionRefused) as caught:
                    delete_job(self.work, LIVE)
                self.assertIn('still running', str(caught.exception))
                self.assertTrue((self.work / 'jobs' / (LIVE + '.json')).exists())
                (self.work / 'jobs' / (LIVE + '.json')).unlink()

    def test_take_lineage_blocks_deletion_until_explicitly_broken(self):
        self.job()
        self.take_using()
        with self.assertRaises(JobDeletionRefused) as caught:
            delete_job(self.work, JOB)
        self.assertIn('origin of 1 saved Take', str(caught.exception))
        self.assertTrue((self.work / 'jobs' / (JOB + '.json')).exists())
        result = delete_job(self.work, JOB, break_lineage=True)
        self.assertEqual(result['takes_orphaned'], ['c' * 32])
        self.assertFalse((self.work / 'jobs' / (JOB + '.json')).exists())

    def test_dashed_uuid_identifiers_are_accepted(self):
        dashed = 'b08fab51-9c28-45d7-88bd-1d31b0b19713'
        self.job(dashed)
        result = delete_job(self.work, dashed)
        self.assertEqual(result['deleted'], dashed)
        self.assertFalse((self.work / 'jobs' / (dashed + '.json')).exists())

    def test_other_jobs_are_untouched(self):
        self.job()
        self.job(LIVE)
        delete_job(self.work, JOB)
        self.assertTrue((self.work / 'jobs' / (LIVE + '.json')).exists())
        self.assertTrue((self.work / 'media' / ('h3-' + LIVE)).is_dir())

    def test_symlinked_media_directory_is_not_followed(self):
        self.job()
        outside = self.work / 'outside'
        outside.mkdir()
        (outside / 'precious.txt').write_text('keep me')
        target = self.work / 'media' / ('h3-' + JOB)
        for child in target.iterdir():
            child.unlink()
        target.rmdir()
        (self.work / 'media' / ('h3-' + JOB)).symlink_to(outside, target_is_directory=True)
        delete_job(self.work, JOB)
        self.assertTrue((outside / 'precious.txt').exists(), 'A symlink must never delete outside the store')


if __name__ == '__main__':
    unittest.main()
