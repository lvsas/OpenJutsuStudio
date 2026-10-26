"""Native Swap collection preserves ordered references and validates retries."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import core
import h3_pipeline as pipeline
import test_h3_native_pipeline as worker_fixture


class NativeReferenceCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.addCleanup(patch.stopall)
        patch.object(core,'WORK',self.root).start()
        self.media=self.root/'media';self.media.mkdir()
        self.folder=self.media/'render';self.folder.mkdir()
        self.refs=[]
        for index,suffix in enumerate(('.png','.jpg')):
            path=self.media/f'input-{index}{suffix}'
            path.write_bytes(bytes([index+1])*20)
            self.refs.append(path)
        self.job=core.Job('a'*32,engine='minimax-h3')
        self.remote=SimpleNamespace(id='sdk-fixture',status='succeeded')
        self.graph={'saved':'fixture'}
        self.recover=patch.object(pipeline,'recover_imported_family',return_value=None).start()
        self.download=patch.object(pipeline,'download_h3_artifacts',
            side_effect=lambda remote,node,folder:folder.mkdir()).start()
        self.revalidate=patch.object(pipeline,'revalidate_downloaded_h3_artifacts').start()
        self.importer=patch.object(pipeline,'import_family',
            return_value=SimpleNamespace(take_id=pipeline.native_operation_id(self.job))).start()

    def collect(self):
        return pipeline._publish_native_take(self.job,self.remote,self.folder,self.media,
                                             self.graph,references=self.refs)

    def test_import_carries_ordered_self_contained_references(self):
        before=[p.read_bytes() for p in self.refs]
        take_id=self.collect()
        self.assertEqual(take_id,pipeline.native_operation_id(self.job))
        kwargs=self.importer.call_args.kwargs
        self.assertEqual(kwargs['root'],self.folder/'native')
        self.assertEqual(kwargs['source_job'],self.job.id)
        carried=kwargs['references']
        self.assertEqual([p.name for p in carried],['reference-1.png','reference-2.jpg'])
        self.assertEqual([p.read_bytes() for p in carried],before)
        self.assertEqual([p.read_bytes() for p in self.refs],before)

    def test_retry_reuses_only_a_validated_matching_published_take(self):
        take_id=pipeline.native_operation_id(self.job)
        self.recover.return_value=SimpleNamespace(record=SimpleNamespace(take_id=take_id))
        self.assertEqual(self.collect(),take_id)
        self.download.assert_not_called();self.importer.assert_not_called()
        self.assertEqual(self.recover.call_args.kwargs['captured_graph'],self.graph)
        self.assertEqual(self.recover.call_args.kwargs['source_job'],self.job.id)

    def test_conflicting_published_take_does_not_download_or_overwrite(self):
        self.recover.side_effect=ValueError('conflicting origin')
        with self.assertRaises(ValueError):self.collect()
        self.download.assert_not_called();self.importer.assert_not_called()

    def test_retained_download_is_revalidated_and_changed_reference_is_preserved(self):
        destination=self.folder/'native';destination.mkdir()
        first=destination/'reference-1.png';first.write_bytes(b'keep-existing')
        with self.assertRaises(ValueError):self.collect()
        self.download.assert_not_called();self.revalidate.assert_called_once()
        self.importer.assert_not_called()
        self.assertEqual(first.read_bytes(),b'keep-existing')


class NativePreflightOrderingTests(unittest.TestCase):
    client: MagicMock
    setUp=worker_fixture.NativePipelineTests.setUp
    run_job=worker_fixture.NativePipelineTests.run_job

    def test_missing_native_node_refuses_before_client_uploads_or_vision(self):
        with patch.object(pipeline,'missing_dependencies',return_value=(['OpenGenjutsuH3PublishClip'],[])):
            job=self.run_job(native_capture=True)
        self.assertEqual(job.status,'error')
        pipeline.make_client.assert_not_called()
        self.client.assets.from_file.assert_not_called()
        self.client.run.assert_not_called()

    def test_unknown_inventory_diagnostic_is_not_returned_as_raw_job_error(self):
        with patch.object(pipeline,'missing_dependencies',side_effect=ValueError('PRIVATE-target-marker')):
            job=self.run_job(native_capture=True)
        self.assertEqual(job.status,'error')
        pipeline.make_client.assert_not_called()
        self.assertNotIn('PRIVATE-target-marker',job.error)

    def test_invalid_weight_profile_refuses_before_client_creation(self):
        job=self.run_job(native_capture=True,weights={})
        self.assertEqual(job.status,'error')
        pipeline.make_client.assert_not_called()


if __name__=='__main__':
    unittest.main()
