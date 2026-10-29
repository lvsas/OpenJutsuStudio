"""Real CPU input guards and exact replay; no network or GPU is ever invoked."""
import copy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import core
import h3_pipeline as pipeline
from h3_capsule import digest_file, freeze_capsule, replay_inputs
from h3_media import ffmpeg
from h3_recipe import bind_frames, make_recipe
from source_clip import extract_excerpt, probe_source


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class SourceGuardPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'media'
        self.media.mkdir()
        self.work_patch = patch.object(core, 'WORK', self.root)
        self.work_patch.start()
        self.addCleanup(self.work_patch.stop)
        self.source = self.media / 'original.mp4'
        self.reference = self.media / 'reference.png'
        self.reference.write_bytes(b'only-used-by-mocked-sdk')
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=96x64:r=24:d=22',
               '-c:v', 'libx264', self.source)
        self.job = core.Job('guard-test', engine='minimax-h3', video=str(self.source))
        self.recipe = make_recipe(preserve_clip='user text', source_width=96, source_height=64,
                                  reference_descriptions=('user character',))
        self.opts = {'recipe': self.recipe, 'reference_images': [self.reference], 'media_dir': self.media}

    def test_direct_worker_long_input_is_refused_before_client_assets_or_refiner(self):
        with patch.object(pipeline, 'make_client') as sdk, \
                patch.object(pipeline, 'prepare_source') as prepare, \
                patch.object(pipeline, '_complete_reference_descriptions') as describe, \
                patch.object(pipeline, '_complete_preserve_clip') as preserve:
            pipeline.run_h3_pipeline(self.job, self.source, self.opts)
        self.assertEqual(self.job.status, 'error')
        self.assertIn('15 seconds', self.job.error)
        sdk.assert_not_called()
        prepare.assert_not_called()
        describe.assert_not_called()
        preserve.assert_not_called()
        self.assertFalse((self.media / f'h3-{self.job.id}').exists())
        self.assertIsNotNone(core.Job.load(self.job.id).finished)

    def test_exact_selected_replay_does_not_extract_or_recompile_recipe(self):
        excerpt = self.media / 'excerpt.mp4'
        info, selection = extract_excerpt(self.source, excerpt, probe_source(self.source), 2, 5)
        recipe = bind_frames(self.recipe, info['frames'], source_audio=False)
        recipe['source_selection'] = selection
        historical_result = self.media / 'historical-result.mp4'
        historical_result.write_bytes(b'capsule-unit-test-result')
        parent = core.Job('parent', engine='minimax-h3', video=str(excerpt),
                          meta={'h3_references': [str(self.reference)],
                                'h3_original_source': str(self.source)})
        freeze_capsule(parent, recipe, excerpt, [self.reference], historical_result, self.media)
        parent.status, parent.result = 'done', str(historical_result)
        parent.save()
        recipe, source, references = replay_inputs(parent, self.media)
        child = core.Job('child', engine='minimax-h3', video=str(source),
                         meta={'parent_job_id': parent.id, 'h3_original_source': str(self.source)})
        client = MagicMock()
        client.assets.from_file.return_value.as_reference.return_value={'__type':'core/ASSET','info':{'id':'mock-asset'}}
        output = MagicMock()
        output.name = 'render.mp4'
        output.to_file.side_effect = lambda destination: Path(destination).write_bytes(b'mocked-render')
        client.run.return_value.get_outputs.return_value = [output]
        def finish(rendered, source, destination, count):
            destination.write_bytes(b'mocked-assembled-result')
            return destination
        before = digest_file(self.source)
        frozen = copy.deepcopy(recipe)
        with patch.object(pipeline, 'make_client', return_value=client), \
                patch.object(pipeline, 'missing_dependencies', return_value=([], [])), \
                patch.object(pipeline, 'download_h3_artifacts', side_effect=lambda remote,node,folder:folder.mkdir()), \
                patch.object(pipeline, 'import_family', return_value=MagicMock(take_id='c'*32)), \
                patch.object(pipeline, 'prepare_source', return_value=(excerpt, 72, 73)) as prepare, \
                patch.object(pipeline, 'has_audio', return_value=False), \
                patch.object(pipeline, 'ffprobe', return_value={'frames': 73}), \
                patch.object(pipeline, 'finish_result', side_effect=finish), \
                patch.object(pipeline, 'validate_result'), \
                patch.object(pipeline, 'bind_frames', side_effect=AssertionError('no recipe rebuild')), \
                patch('source_clip.extract_excerpt', side_effect=AssertionError('no second trim')):
            pipeline.run_h3_pipeline(child, source,
                                     {'recipe': recipe, 'reference_images': references,
                                      'media_dir': self.media, 'input_hashes': {'source': digest_file(source)}})
        self.assertEqual(child.status, 'done', child.error)
        self.assertEqual(client.run.call_count, 1)
        self.assertEqual(prepare.call_args.args[0], excerpt)
        self.assertEqual(client.assets.from_file.call_args_list[0].args[0], excerpt)
        self.assertEqual(child.meta['h3_capsule']['recipe'], frozen)
        self.assertEqual(child.meta['source_info']['duration'], 3)
        self.assertEqual(child.meta['source_shot_plan'], [{'start': 0, 'end': 71, 'fps': 24}])
        self.assertEqual(digest_file(self.source), before)

    def test_queued_effective_input_tampering_is_refused_before_sdk(self):
        excerpt = self.media / 'excerpt.mp4'
        extract_excerpt(self.source, excerpt, probe_source(self.source), 2, 5)
        with patch.object(pipeline, 'make_client') as sdk:
            pipeline.run_h3_pipeline(self.job, excerpt, self.opts | {'input_hashes': {'source': 'wrong'}})
        self.assertEqual(self.job.status, 'error')
        self.assertIn('queued input changed', self.job.error)
        sdk.assert_not_called()


if __name__ == '__main__':
    unittest.main()
