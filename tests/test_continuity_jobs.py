"""SDK-operation checkpoint tests; remote jobs are explicit unit doubles."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_jobs as jobs


class OperationTests(unittest.TestCase):
    op = 'a' * 32
    target = 'b' * 64

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.graph = {'capture': {'class_type': 'SaveText', 'inputs': {
            'text': 'PRIVATE_CAPTURE', 'filename_prefix': 'private/capture', 'format': 'txt'}}}
        self.remote = SimpleNamespace(id='actual-remote-id', status='succeeded', wait=Mock())
        self.client = SimpleNamespace(submit=Mock(return_value=self.remote),
                                      jobs=SimpleNamespace(get=Mock(return_value=self.remote)))
        self.collect = Mock(return_value='c' * 32)
        self.create()

    def create(self, **overrides):
        return jobs.create_operation(self.root, self.op, **{
            'graph': self.graph, 'mode': 'root', 'seed': 41,
            'target_fingerprint': self.target, **overrides})

    def execute(self, **overrides):
        return jobs.execute_operation(self.root, self.op, self.client, **{
            'target_fingerprint': self.target, 'collect': self.collect, **overrides})

    def test_frozen_intent_idempotent_and_public_view_has_no_private_material(self):
        self.assertEqual(self.create()['status'], 'queued')
        with self.assertRaises(ValueError):
            self.create(seed=42)
        self.graph['capture']['inputs']['text'] = 'CHANGED'
        record = jobs._read(jobs._path(self.root, self.op))
        self.assertEqual(record['intent']['graph']['capture']['inputs']['text'], 'PRIVATE_CAPTURE')
        self.assertNotIn('PRIVATE', str(jobs.get_operation(self.root, self.op)))
        self.assertNotIn(self.target, str(jobs.get_operation(self.root, self.op)))

    def test_persists_remote_identity_before_wait_and_done_never_resubmits(self):
        def wait(**kwargs):
            record = jobs._read(jobs._path(self.root, self.op))
            self.assertEqual(record['remote_job_id'], self.remote.id)
            self.assertEqual(record['status'], 'waiting')
        self.remote.wait.side_effect = wait
        view = self.execute()
        self.assertEqual(view['status'], 'done')
        self.assertEqual(view['take_id'], 'c' * 32)
        self.assertEqual(self.execute(), view)
        self.client.submit.assert_called_once()
        self.assertEqual(self.client.submit.call_args.kwargs,
                         {'idempotency_key': 'opengenjutsu-native-' + self.op})
        self.collect.assert_called_once()

    def test_ambiguous_submit_stops_second_post_with_same_durable_key(self):
        self.client.submit.side_effect = TimeoutError('PRIVATE URL secret')
        for _ in range(2):
            with self.assertRaises(jobs.OperationUncertain) as error:
                self.execute()
            self.assertEqual(error.exception.operation_id, self.op)
            self.assertNotIn('PRIVATE', str(error.exception))
        self.client.submit.assert_called_once()
        self.assertEqual(jobs.get_operation(self.root, self.op)['status'], 'uncertain')

    def test_wait_timeout_and_collection_failure_resume_known_job_without_submit(self):
        self.remote.wait.side_effect = TimeoutError('wait expired')
        with self.assertRaises(TimeoutError):
            self.execute()
        self.remote.wait.side_effect = None
        self.collect.side_effect = OSError('collection failed')
        with self.assertRaises(OSError):
            self.execute()
        self.collect.side_effect = None
        self.assertEqual(self.execute()['status'], 'done')
        self.client.submit.assert_called_once()
        self.assertEqual(self.client.jobs.get.call_count, 2)
        self.assertEqual(self.collect.call_count, 2)

    def test_failed_remote_is_terminal_without_collecting(self):
        self.remote.status = 'failed'
        self.assertEqual(self.execute()['status'], 'error')
        self.execute()
        self.client.submit.assert_called_once()
        self.collect.assert_not_called()

    def test_target_mismatch_or_corrupt_intent_never_submits(self):
        with self.assertRaises(ValueError):
            self.execute(target_fingerprint='d' * 64)
        path = jobs._path(self.root, self.op)
        import json
        record = json.loads(path.read_text())
        record['intent']['seed'] = 40
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            self.execute()
        self.client.submit.assert_not_called()

    def test_wrong_remote_identity_on_resume_is_rejected_before_collection(self):
        self.remote.wait.side_effect = TimeoutError('pause')
        with self.assertRaises(TimeoutError):
            self.execute()
        self.client.jobs.get.return_value = SimpleNamespace(id='other-job', status='succeeded', wait=Mock())
        with self.assertRaises(ValueError):
            self.execute()
        self.collect.assert_not_called()
        self.client.submit.assert_called_once()

    def test_remote_checkpoint_failure_preserves_known_id_without_second_submit(self):
        original = jobs._write
        def write(path, record):
            if record['remote_job_id']:
                raise jobs.OperationUncertain(record['id'], record['remote_job_id'])
            return original(path, record)
        with patch.object(jobs, '_write', side_effect=write):
            with self.assertRaises(jobs.OperationUncertain) as error:
                self.execute()
            self.assertEqual(error.exception.remote_job_id, self.remote.id)
        with self.assertRaises(jobs.OperationUncertain):
            self.execute()
        self.remote.wait.assert_not_called()
        self.client.submit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
