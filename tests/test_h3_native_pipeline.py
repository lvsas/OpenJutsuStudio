"""The native family must be captured inside the Swap's own SDK job.

One submission, two sets of outputs: the visible MP4 the Swap already produced
and the MP4/MCTX/COND family published by the node pack. A second submission
would sample the take twice and bill the GPU twice, so these cases pin the
call count before anything else.
"""
import copy
from dataclasses import asdict
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import core
import h3_pipeline as pipeline
from h3_graphs import H3Models
from h3_recipe import make_recipe

WEIGHT_ROLES = asdict(H3Models())


class NativePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.addCleanup(patch.stopall)
        patch.object(core, 'WORK', self.root).start()
        self.media = self.root / 'media'
        self.media.mkdir()
        self.source = self.media / 'source.mp4'
        self.reference = self.media / 'ref.png'
        self.source.write_bytes(b'source')
        self.reference.write_bytes(b'reference')
        self.recipe = make_recipe('  user text\n', 123, source_width=640, source_height=360)
        self.job = core.Job('h3-native', engine='minimax-h3', video=str(self.source),
                            meta={'h3_references': [str(self.reference)]})
        self.opts = {'recipe': self.recipe, 'reference_images': [self.reference],
                     'media_dir': self.media}
        self.weights = {role: {'filename': name, 'sha256': '1' * 64}
                        for role, name in WEIGHT_ROLES.items()}

        self.client = MagicMock()
        # as_reference() returns a committed SDK asset, not a bare string.
        self.client.assets.from_file.return_value.as_reference.return_value = {
            '__type': 'core/ASSET', 'info': {'id': 'asset-ref'}}
        image, video = MagicMock(), MagicMock()
        image.name, video.name = 'preview.png', 'movie.mp4'
        video.to_file.side_effect = lambda p: Path(p).write_bytes(b'movie')
        # from_json returns the workflow built from that exact graph, as the SDK does.
        self.client.workflows.from_json.side_effect = lambda graph: graph
        self.remote = self.client.run.return_value
        self.remote.status = 'succeeded'
        self.remote.get_outputs.return_value = [image, video]

        self.download = patch.object(pipeline, 'download_h3_artifacts').start()
        self.import_family = patch.object(pipeline, 'import_family').start()
        self.import_family.return_value = MagicMock(take_id='c' * 32)

        patch.object(pipeline, 'make_client', return_value=self.client).start()
        patch.object(pipeline, 'prepare_source', return_value=(self.source, 23, 39)).start()
        patch.object(pipeline, 'has_audio', return_value=False).start()
        patch.object(pipeline, 'ffprobe', return_value={'frames': 39, 'fps': 24}).start()

        def finish(rendered, source, destination, count):
            destination.write_bytes(b'final')
            return destination
        patch.object(pipeline, 'finish_result', side_effect=finish).start()
        patch.object(pipeline, 'validate_result').start()

    def run_job(self, **extra):
        pipeline.run_h3_pipeline(self.job, self.source, self.opts | extra)
        return core.Job.load(self.job.id)

    def submitted_graph(self):
        return self.client.run.call_args.args[0]

    def test_legacy_swap_never_builds_or_downloads_a_native_family(self):
        job = self.run_job()
        self.assertEqual(job.status, 'done')
        self.assertEqual(self.client.run.call_count, 1)
        graph = self.submitted_graph()
        self.assertNotIn('native_swap_save', graph)
        self.assertNotIn('native_swap_family', graph)
        self.download.assert_not_called()
        self.import_family.assert_not_called()
        self.assertNotIn('native_take_id', job.meta)

    def test_native_capture_submits_once_and_reads_every_output_from_that_job(self):
        job = self.run_job(native_capture=True, weights=self.weights)
        self.assertEqual(job.status, 'done')
        self.assertEqual(self.client.run.call_count, 1, 'the Swap must be sampled once')
        graph = self.submitted_graph()
        self.assertIn('native_swap_save', graph)
        self.assertIn('native_swap_family', graph)
        self.assertEqual(graph['native_swap_family']['class_type'], 'OpenGenjutsuH3PublishClip')
        self.assertTrue(graph['native_swap_save']['inputs']['save_conditioning'])
        # The same remote job publishes both the display MP4 and the family.
        self.download.assert_called_once()
        args = self.download.call_args
        self.assertIs(args.args[0], self.remote)
        self.assertEqual(args.args[1], 'native_swap_family')
        self.assertEqual(job.meta['native_take_id'], 'c' * 32)

    def test_absent_weight_profile_is_recorded_as_filename_identity_only(self):
        """Nobody can hash tens of gigabytes on a hosted target; that must not block."""
        job = self.run_job(native_capture=True)
        self.assertEqual(job.status, 'done')
        self.assertEqual(self.client.run.call_count, 1)
        self.assertIn('native_take_id', job.meta)

    def test_a_supplied_profile_never_invents_a_measured_hash(self):
        for weights in ({}, {'unet': {'filename': WEIGHT_ROLES['unet']}},
                        {'unet': {'filename': WEIGHT_ROLES['unet'], 'sha256': 42}}):
            with self.subTest(weights=str(weights)[:40]):
                job = self.run_job(native_capture=True, weights=weights)
                self.assertEqual(job.status, 'error')
                self.client.run.assert_not_called()

    def test_the_visible_result_and_the_native_take_stay_distinct(self):
        job = self.run_job(native_capture=True, weights=self.weights)
        self.assertEqual(job.status, 'done')
        self.assertNotEqual(job.meta['native_take_id'], Path(job.result).stem,
                            'a Take id is not the displayed file')
        self.assertEqual(job.result, str((self.media / f"h3-{job.id}" / 'result.mp4').resolve()))

    def test_native_capture_is_opt_in_and_never_enabled_implicitly(self):
        for value in (False, 'true', 1, None):
            with self.subTest(value=value):
                self.setUp()
                job = self.run_job(native_capture=value, weights=self.weights)
                self.assertEqual(job.status, 'done')
                self.assertNotIn('native_swap_save', self.submitted_graph())

    def test_a_failed_family_publication_does_not_report_a_native_success(self):
        self.download.side_effect = ValueError('SDK node has not published the complete family')
        job = self.run_job(native_capture=True, weights=self.weights)
        self.assertEqual(job.status, 'error')
        self.assertNotIn('native_take_id', job.meta)


if __name__ == '__main__':
    unittest.main()
