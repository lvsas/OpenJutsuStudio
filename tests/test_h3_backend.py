"""H3-only runner/capsule contracts; SDK is mocked, never submitted."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import core
import h3_capsule as capsule
import h3_pipeline as pipeline
from h3_recipe import make_recipe


class BackendTests(unittest.TestCase):
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
        self.job = core.Job('h3-test', engine='minimax-h3', video=str(self.source),
                            meta={'h3_reference': str(self.reference)})
        self.opts = {'recipe': self.recipe, 'reference_image': self.reference,
                     'media_dir': self.media}
        self.client = MagicMock()
        self.client.assets.from_file.return_value.as_reference.return_value = 'asset-ref'
        image, video = MagicMock(), MagicMock()
        image.name, video.name = 'preview.png', '../../movie.mp4'
        video.to_file.side_effect = lambda p: Path(p).write_bytes(b'movie')
        self.client.run.return_value.get_outputs.return_value = [image, video]
        self.video = video
        patch.object(pipeline, 'make_client', return_value=self.client).start()
        patch.object(pipeline, 'prepare_source', return_value=(self.source, 23, 39)).start()
        patch.object(pipeline, 'has_audio', return_value=False).start()
        patch.object(pipeline, 'ffprobe', return_value={'frames': 39, 'fps': 24}).start()
        def finish(rendered, source, destination, count):
            destination.write_bytes(b'final')
            return destination
        patch.object(pipeline, 'finish_result', side_effect=finish).start()
        patch.object(pipeline, 'validate_result').start()

    def run_job(self):
        pipeline.run_h3_pipeline(self.job, self.source, self.opts)
        return core.Job.load(self.job.id)

    def test_preserve_generation_completes_the_recipe_and_warns_on_failure(self):
        blank = make_recipe(source_width=640, source_height=360)
        with patch.object(pipeline, 'describe_preserved',
                          return_value={'text': 'the staff and the snow', 'model': 'm',
                                        'frames': 4, 'job_id': 'j'}):
            completed, warning = pipeline._complete_preserve_clip(None, blank, self.source, self.root)
        self.assertIsNone(warning)
        self.assertEqual(completed['preserve_clip'], 'the staff and the snow')
        self.assertEqual(completed['preserve_clip_source'], 'generated')
        with patch.object(pipeline, 'describe_preserved', side_effect=RuntimeError('model unavailable')):
            kept, warning = pipeline._complete_preserve_clip(None, blank, self.source, self.root)
        self.assertEqual((kept['preserve_clip'], kept['preserve_clip_source']), ('', 'none'))
        self.assertIn('not described', warning)
        # An operator's own text is never sent to the model at all.
        authored = make_recipe(preserve_clip='keep the scarf', source_width=640, source_height=360)
        with patch.object(pipeline, 'describe_preserved', side_effect=AssertionError('must not run')):
            same, warning = pipeline._complete_preserve_clip(None, authored, self.source, self.root)
        self.assertIsNone(warning)
        self.assertEqual(same['preserve_clip'], 'keep the scarf')

    def test_reference_description_is_generated_and_never_overwrites_the_operator(self):
        blank = make_recipe(source_width=640, source_height=360)
        with patch.object(pipeline, 'describe_character',
                          return_value={'text': 'a tall woman in a red coat', 'model': 'm',
                                        'frames': 1, 'job_id': 'j'}):
            completed, warning = pipeline._complete_reference_descriptions(
                None, blank, [self.reference], self.root)
        self.assertIsNone(warning)
        self.assertEqual(completed['reference_descriptions'], ['a tall woman in a red coat'])
        self.assertEqual(completed['reference_description_sources'], ['generated'])
        self.assertIn('<Picture 1>: a tall woman in a red coat.', completed['effective_prompt'])
        authored = make_recipe(preserve_clip='keep the scarf', source_width=640, source_height=360,
                               reference_descriptions=('already described',))
        with patch.object(pipeline, 'describe_character', side_effect=AssertionError('must not run')):
            same, warning = pipeline._complete_reference_descriptions(
                None, authored, [self.reference], self.root)
        self.assertIsNone(warning)
        self.assertEqual(same['reference_descriptions'], ['already described'])
        with patch.object(pipeline, 'describe_character', side_effect=RuntimeError('no vision node')):
            kept, warning = pipeline._complete_reference_descriptions(
                None, blank, [self.reference], self.root)
        self.assertEqual(kept['reference_descriptions'], [''])
        self.assertIn('Character 1 was not described', warning)

    def test_success_is_h3_only_and_selects_mp4(self):
        with patch.object(core, 'edit_segment', side_effect=AssertionError('LTX forbidden')):
            job = self.run_job()
        self.assertEqual(job.status, 'done', job.error)
        self.assertIsNotNone(job.finished)
        self.client.close.assert_called_once()
        self.video.to_file.assert_called_once()
        self.client.run.return_value.get_outputs.assert_called_once_with('156')
        graph = self.client.workflows.from_json.call_args.args[0]
        self.assertIn('MiniMaxH3ReferenceToVideo', [n['class_type'] for n in graph.values()])
        self.assertFalse(any('Ripple' in n['class_type'] or 'Flux' in n['class_type'] for n in graph.values()))
        self.assertNotIn('audio', graph['156']['inputs'])
        self.assertNotIn('ref_video_audios.ref_video_audio_0', graph['136']['inputs'])
        self.assertEqual(graph['155']['inputs']['frame_load_cap'], 39)
        frozen = job.meta['h3_capsule']
        self.assertEqual(frozen['recipe']['preserve_clip'], '  user text\n')
        self.assertEqual(set(frozen['assets']), {'source', 'reference', 'result'})
        self.assertNotIn(str(self.root), json.dumps(frozen))
        recipe, source, ref = capsule.replay_inputs(job, self.media)
        self.assertEqual(recipe, frozen['recipe'])
        self.assertEqual((source, ref), (self.source, self.reference))

    def test_replay_uses_frozen_graph_not_current_builder(self):
        parent = self.run_job()
        recipe, source, reference = capsule.replay_inputs(parent, self.media)
        frozen_graph = copy.deepcopy(parent.meta['h3_capsule']['recipe']['graph_template'])
        child = core.Job('h3-child', engine='minimax-h3', video=str(source),
                         meta={'h3_reference': str(reference), 'parent_job_id': parent.id})
        with patch.object(pipeline, 'bind_frames', side_effect=AssertionError('must not rebuild')):
            pipeline.run_h3_pipeline(child, source, dict(self.opts, recipe=recipe))
        self.assertEqual(child.status, 'done', child.error)
        self.assertEqual(child.meta['h3_capsule']['recipe']['graph_template'], frozen_graph)
        self.assertEqual(child.meta['h3_capsule']['parent_job_id'], parent.id)

    def test_input_changed_while_rendering_is_not_success(self):
        self.video.to_file.side_effect = lambda p: (Path(p).write_bytes(b'movie'),
                                                   self.source.write_bytes(b'mutated'))
        self.assertEqual(self.run_job().status, 'error')

    def test_failed_download_never_done(self):
        self.video.to_file.side_effect = RuntimeError('download failed')
        job = self.run_job()
        self.assertEqual(job.status, 'error')
        self.assertIsNone(job.result)
        self.assertIsNotNone(job.finished)
        self.assertNotIn('h3_capsule', job.meta)
        self.client.close.assert_called_once()
        self.assertFalse(list(self.media.rglob('*.part')))

    def test_corrupt_result_never_done(self):
        pipeline.validate_result.side_effect = ValueError('invalid video')
        self.assertEqual(self.run_job().status, 'error')

    def test_replay_rejects_mutated_input_and_recipe(self):
        job = self.run_job()
        original = copy.deepcopy(job.meta)
        job.meta['h3_capsule']['recipe']['seed'] = 999
        with self.assertRaises(ValueError):
            capsule.replay_inputs(job, self.media)
        job.meta = original
        self.reference.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            capsule.replay_inputs(job, self.media)

    def test_containment_rejects_escape_and_symlink(self):
        outside = self.root / 'outside.png'
        outside.write_bytes(b'image')
        link = self.media / 'link.png'
        link.symlink_to(outside)
        for path in (outside, link, self.media / '../outside.png'):
            with self.assertRaises(ValueError):
                capsule.contained(path, self.media)

    def test_missing_reference_fails_without_submission(self):
        self.reference.unlink()
        job = self.run_job()
        self.assertEqual(job.status, 'error')
        self.client.run.assert_not_called()
        self.assertIsNotNone(job.finished)

    def test_empty_outputs_are_not_a_result(self):
        self.client.run.return_value.get_outputs.return_value = []
        job = self.run_job()
        self.assertEqual(job.status, 'error')
        self.assertIsNone(job.result)
        self.client.close.assert_called_once()

    def test_queued_input_hash_mismatch_blocks_submission(self):
        self.opts['input_hashes'] = {'source': 'wrong'}
        self.assertEqual(self.run_job().status, 'error')
        self.client.run.assert_not_called()

    def test_wrong_engine_never_submits(self):
        self.job.engine = 'ltx25-ripple'
        self.assertEqual(self.run_job().status, 'error')
        self.client.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()