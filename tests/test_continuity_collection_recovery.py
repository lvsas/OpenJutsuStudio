"""Real file/registry recovery with synthetic SDK bytes and mocked media probe.

No GPU, network requests or live Take-store mutations occur in these tests.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_jobs as jobs
import continuity_pipeline as pipeline
from continuable_take import get_validated_family
from tests import test_h3_artifact_transport as fixtures


class CollectionRecoveryTests(unittest.TestCase):
    operation = 'a' * 32
    fingerprint = 'f' * 64

    def setUp(self):
        self.fixture = fixtures.DownloadTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.work = self.fixture.root / 'work'
        self.folder = self.fixture.destination
        self.graph = {'capture': {'class_type': 'SaveText', 'inputs': {
            'text': 'Private synthetic capture', 'filename_prefix': 'unit/capture', 'format': 'txt'}}}
        self.fixture.outputs = [self.fixture.output(role, node_id=pipeline.FAMILY_NODE)
                                for role in self.fixture.data]
        self.remote = self.fixture.job
        self.remote.wait = MagicMock()
        self.client = MagicMock()
        self.client.submit.return_value = self.remote
        self.client.jobs.get.return_value = self.remote
        jobs.create_operation(self.work, self.operation, mode='forward', graph=self.graph,
            seed=7, parents=('b' * 32,), target_fingerprint=self.fingerprint)
        self.collect = pipeline.collect_forward(self.work, self.folder, compiled_graph=self.graph)

    def execute(self, collect=None):
        return jobs.execute_operation(self.work, self.operation, self.client,
            target_fingerprint=self.fingerprint, collect=collect or self.collect)

    def fail_import_once(self):
        real_import = pipeline.import_family
        calls = 0
        def import_family(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError('synthetic transient publication failure')
            return real_import(*args, **kwargs)
        return import_family

    def test_retry_reuses_valid_download_after_import_failure_without_resampling(self):
        with patch.object(pipeline, 'import_family', side_effect=self.fail_import_once()) as publish, \
             patch.object(pipeline, 'download_h3_artifacts', wraps=pipeline.download_h3_artifacts) as download:
            with self.assertRaises(OSError):
                self.execute()
            self.assertEqual(jobs.get_operation(self.work, self.operation)['status'], 'collecting')
            retained = {path.name: path.read_bytes() for path in self.folder.iterdir()}
            result = self.execute()
            self.assertEqual(result['status'], 'done')
            self.assertEqual(download.call_count, 1)
            self.assertEqual(publish.call_count, 2)
            self.assertEqual(retained, {path.name: path.read_bytes() for path in self.folder.iterdir()})
        self.client.submit.assert_called_once()
        self.client.jobs.get.assert_called_once_with(self.remote.id)
        self.assertEqual(get_validated_family(self.work, self.operation).record.take_id, self.operation)

    def test_retry_recovers_already_published_take_after_final_checkpoint_failure(self):
        real_write = jobs._write
        interrupted = False
        def write(path, record):
            nonlocal interrupted
            if record['status'] == 'done' and not interrupted:
                interrupted = True
                raise OSError('synthetic lost final acknowledgement')
            return real_write(path, record)
        with patch.object(jobs, '_write', side_effect=write), \
             patch.object(pipeline, 'import_family', wraps=pipeline.import_family) as publish, \
             patch.object(pipeline, 'download_h3_artifacts', wraps=pipeline.download_h3_artifacts) as download:
            with self.assertRaises(OSError):
                self.execute()
            self.assertEqual(jobs.get_operation(self.work, self.operation)['status'], 'collecting')
            self.assertEqual(get_validated_family(self.work, self.operation).record.take_id, self.operation)
            self.assertEqual(self.execute()['status'], 'done')
            self.assertEqual(publish.call_count, 1)
            self.assertEqual(download.call_count, 1)
        self.client.submit.assert_called_once()

    def test_corrupted_retained_download_is_not_replaced_or_imported(self):
        with patch.object(pipeline, 'import_family', side_effect=OSError('temporary')):
            with self.assertRaises(OSError): self.execute()
        target = self.folder / 'take.mp4'
        target.write_bytes(b'corrupted synthetic bytes')
        with patch.object(pipeline, 'import_family') as publish, \
             patch.object(pipeline, 'download_h3_artifacts') as download:
            with self.assertRaises(ValueError): self.execute()
            publish.assert_not_called(); download.assert_not_called()
        self.assertEqual(target.read_bytes(), b'corrupted synthetic bytes')
        self.client.submit.assert_called_once()

    def test_reference_copy_is_reused_and_published_references_recover_without_sources(self):
        source = self.fixture.root / 'reference.png'
        source.write_bytes(b'synthetic reference image')
        collect = pipeline.collect_forward(self.work, self.folder, compiled_graph=self.graph,
                                           reference_paths=(source,))
        with patch.object(pipeline, 'import_family', side_effect=self.fail_import_once()):
            with self.assertRaises(OSError): self.execute(collect)
            retained = self.folder / 'reference-1.png'
            fingerprint = retained.stat().st_mtime_ns
            self.assertEqual(self.execute(collect)['status'], 'done')
            self.assertEqual(retained.stat().st_mtime_ns, fingerprint)
        source.rename(source.with_suffix('.archived'))
        self.folder.rename(self.folder.with_name('archived-download'))
        self.assertEqual(collect(self.remote, None, self.operation), self.operation)
        published = get_validated_family(self.work, self.operation).video.parent / 'reference-1.png'
        published.chmod(0o600)
        published.write_bytes(b'changed published identity')
        with self.assertRaises(ValueError): collect(self.remote, None, self.operation)

    def interrupted_reference_open(self, *, abort=False):
        original = Path.open
        folder = self.folder
        @contextmanager
        def opened(path, *args, **kwargs):
            with original(path, *args, **kwargs) as stream:
                if path.parent != folder or 'reference-1.png' not in path.name or args != ('xb',):
                    yield stream
                    return
                class PartialWriter:
                    def write(self, data):
                        stream.write(data[:3]); stream.flush()
                        if abort:
                            os._exit(17)
                        raise OSError('interrupted reference copy')
                yield PartialWriter()
        return opened

    def test_interrupted_reference_write_never_publishes_a_partial_final_file(self):
        source = self.fixture.root / 'reference.png'
        source.write_bytes(b'synthetic reference image')
        collect = pipeline.collect_forward(self.work, self.folder, compiled_graph=self.graph,
                                           reference_paths=(source,))
        with patch.object(Path, 'open', self.interrupted_reference_open()):
            with self.assertRaisesRegex(OSError, 'interrupted reference copy'):
                self.execute(collect)
        self.assertFalse((self.folder / 'reference-1.png').exists())
        self.assertEqual(self.execute(collect)['status'], 'done')
        self.assertEqual((self.folder / 'reference-1.png').read_bytes(), source.read_bytes())
        self.client.submit.assert_called_once()

    @unittest.skipUnless(hasattr(os, 'fork'), 'process-death fixture requires POSIX')
    def test_process_death_during_reference_copy_recovers_without_resubmission(self):
        source = self.fixture.root / 'reference.png'
        source.write_bytes(b'synthetic reference image')
        collect = pipeline.collect_forward(self.work, self.folder, compiled_graph=self.graph,
                                           reference_paths=(source,))
        pid = os.fork()
        if pid == 0:
            with patch.object(Path, 'open', self.interrupted_reference_open(abort=True)):
                self.execute(collect)
            os._exit(99)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 17)
        self.assertFalse((self.folder / 'reference-1.png').exists())
        self.assertEqual(jobs.get_operation(self.work, self.operation)['status'], 'collecting')
        self.assertEqual(self.execute(collect)['status'], 'done')
        self.client.submit.assert_not_called()  # The child already persisted its remote job.
        self.client.jobs.get.assert_called_once_with(self.remote.id)
        self.assertEqual((self.folder / 'reference-1.png').read_bytes(), source.read_bytes())

    def test_changed_retained_reference_is_not_overwritten_on_retry(self):
        source = self.fixture.root / 'reference.png'
        source.write_bytes(b'synthetic reference image')
        collect = pipeline.collect_forward(self.work, self.folder, compiled_graph=self.graph,
                                           reference_paths=(source,))
        with patch.object(pipeline, 'import_family', side_effect=OSError('temporary')):
            with self.assertRaises(OSError): self.execute(collect)
        retained = self.folder / 'reference-1.png'
        retained.write_bytes(b'changed retained identity')
        with patch.object(pipeline, 'import_family') as publish:
            with self.assertRaises(ValueError): self.execute(collect)
            publish.assert_not_called()
        self.assertEqual(retained.read_bytes(), b'changed retained identity')
        self.client.submit.assert_called_once()

    def test_local_download_from_another_remote_job_is_refused(self):
        with patch.object(pipeline, 'import_family', side_effect=OSError('temporary')):
            with self.assertRaises(OSError): self.execute()
        manifest = self.folder / 'manifest.json'
        payload = json.loads(manifest.read_text())
        payload['sdk_source'] = {'job_id': 'another-job', 'node_id': pipeline.FAMILY_NODE}
        manifest.write_text(json.dumps(payload))
        with patch.object(pipeline, 'import_family') as publish:
            with self.assertRaises(ValueError): self.execute()
            publish.assert_not_called()
        self.client.submit.assert_called_once()

    def test_existing_take_must_match_job_graph_label_and_preserved_bytes(self):
        self.assertEqual(self.execute()['status'], 'done')
        for changed in ('job', 'graph', 'label', 'bytes'):
            with self.subTest(changed=changed):
                graph = self.graph if changed != 'graph' else {'other': self.graph['capture']}
                label = 'native-prepend' if changed == 'label' else 'native-forward'
                collector = pipeline.collect_forward(self.work, self.folder,
                    compiled_graph=graph, operator_label=label)
                remote = self.remote
                if changed == 'job':
                    remote = MagicMock(id='another-job', status='succeeded')
                if changed == 'bytes':
                    path = get_validated_family(self.work, self.operation).video
                    path.chmod(0o600)
                    path.write_bytes(b'corrupted published fixture')
                with patch.object(pipeline, 'download_h3_artifacts') as download, \
                     patch.object(pipeline, 'import_family') as publish:
                    with self.assertRaises(ValueError): collector(remote, None, self.operation)
                    download.assert_not_called(); publish.assert_not_called()

    def test_legacy_unassociated_download_is_kept_and_refused_not_silently_adopted(self):
        with patch.object(pipeline, 'import_family', side_effect=OSError('temporary')):
            with self.assertRaises(OSError): self.execute()
        manifest = self.folder / 'manifest.json'
        payload = json.loads(manifest.read_text())
        payload.pop('sdk_source', None)
        manifest.write_text(json.dumps(payload))
        with patch.object(pipeline, 'download_h3_artifacts') as download, \
             patch.object(pipeline, 'import_family') as publish:
            with self.assertRaises(ValueError): self.execute()
            download.assert_not_called(); publish.assert_not_called()
        self.assertTrue(manifest.exists())
