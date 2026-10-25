"""H3 HTTP contracts without GPU, external services, or app.py integration."""

import copy
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import core
import h3_api
from h3_capsule import freeze_capsule
from h3_graphs import REFERENCE_SLOTS
from h3_recipe import bind_frames
from h3_capsule import digest_file
from h3_media import ffmpeg
import h3_pipeline


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'media'
        self.media.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(core, 'WORK', self.root).start()
        self.ready = MagicMock(return_value={'ready': True, 'issues': []})
        self.dispatch = MagicMock()
        app = FastAPI()
        app.include_router(h3_api.create_router(lambda: self.media, 4096, self.ready, self.dispatch))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.source_info = {'frames': 24, 'fps': 24, 'duration': 1, 'width': 64, 'height': 64}
        patch.object(h3_api, 'probe_source', side_effect=lambda path: dict(self.source_info)).start()
        patch.object(h3_api, 'require_short_source', side_effect=lambda path: dict(self.source_info)).start()
        async def save(video, destination, limit):
            destination.write_bytes(await video.read())
            return {'frames': 24, 'fps': 24, 'duration': 1, 'width': 64, 'height': 64}
        async def reference(upload, destination, limit):
            data = await upload.read()
            if not data or data == b'invalid':
                from fastapi import HTTPException
                raise HTTPException(422, 'Invalid reference')
            destination.write_bytes(data)
        patch.object(h3_api, 'save_video', side_effect=save).start()
        patch.object(h3_api, 'save_reference', side_effect=reference).start()


    def submit(self, reference=b'image', **kwargs):
        files = [('video', ('../../source.mp4', b'video', 'video/mp4'))]
        if reference is not None:
            files.append(('reference_images', ('../../ref.png', reference, 'image/png')))
        return self.client.post('/api/h3/jobs', files=files, **kwargs)

    def test_reference_required_invalid_and_valid(self):
        self.assertEqual(self.submit(None).status_code, 422)
        self.assertEqual(self.submit(b'invalid').status_code, 422)
        self.assertFalse(list(self.media.iterdir()))
        response = self.submit(data={'edit_prompt': '  exact\n', 'seed': '42'})
        self.assertEqual(response.status_code, 202, response.text)
        job, source, opts = self.dispatch.call_args.args
        self.assertEqual(self.client.get('/api/h3/readiness').json(),
                         {'ready': True, 'issues': [], 'limits': {'max_clip_seconds': 15}})
        self.assertEqual(self.client.get(f'/api/h3/jobs/{job.id}/source').content, b'video')
        self.assertEqual(self.client.get(f'/api/h3/jobs/{job.id}/reference').content, b'image')
        self.assertEqual(job.engine, 'minimax-h3')
        self.assertEqual(opts['recipe']['preserve_clip'], '  exact\n')
        self.assertEqual(opts['recipe']['seed'], 42)
        self.assertEqual(source.parent, self.media)
        self.assertEqual(Path(opts['reference_images'][0]).parent, self.media)
        self.assertNotIn(str(self.root), response.text)
        self.assertEqual(self.client.get(f'/api/h3/jobs/{job.id}/capsule').status_code, 409)

    def test_shipped_form_description_reaches_dispatch_verbatim(self):
        # Use the production field name, not an independently invented API payload.
        html = (Path(__file__).resolve().parents[1] / 'src/templates/h3.html').read_text()
        field = re.search(r'id="h3-description" name="([^"]+)"', html)
        self.assertIsNotNone(field, 'The shipped description control must have a public name')
        assert field is not None
        name = field[1]
        text = '  cheveux bruns\n veste orange  '
        response = self.submit(data={name: text, 'edit_prompt': '  keep jacket\n'})
        self.assertEqual(response.status_code, 202, response.text)
        job, _, opts = self.dispatch.call_args.args
        self.assertEqual(opts['recipe']['reference_descriptions'], [text])
        self.assertEqual(opts['recipe']['reference_description_sources'], ['user'])
        self.assertEqual(opts['recipe']['preserve_clip'], '  keep jacket\n')
        self.assertIn(text.strip(), opts['recipe']['effective_prompt'])
        self.assertEqual(core.Job.load(job.id).meta['h3_recipe'], opts['recipe'])

    def test_ordered_descriptions_match_two_public_reference_uploads(self):
        texts = ['  first character\n', '\nsecond character  ']
        files = [('video', ('source.mp4', b'video', 'video/mp4')),
                 ('reference_images', ('first.png', b'first image', 'image/png')),
                 ('reference_images', ('second.png', b'second image', 'image/png'))]
        response = self.client.post('/api/h3/jobs', files=files,
                                    data={'character_descriptions': texts})
        self.assertEqual(response.status_code, 202, response.text)
        job, _, opts = self.dispatch.call_args.args
        self.assertEqual(opts['recipe']['reference_count'], 2)
        self.assertEqual(opts['recipe']['reference_descriptions'], texts)
        self.assertEqual(opts['recipe']['reference_description_sources'], ['user', 'user'])
        self.assertEqual([Path(path).read_bytes() for path in opts['reference_images']],
                         [b'first image', b'second image'])
        self.assertLess(job.prompt.index('first character'), job.prompt.index('second character'))
        self.assertEqual(core.Job.load(job.id).meta['h3_recipe'], opts['recipe'])
        # The existing UI has one description: it belongs to reference 1 only.
        response = self.client.post('/api/h3/jobs', files=files,
                                    data={'character_description': texts[0]})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.dispatch.call_args.args[2]['recipe']['reference_descriptions'],
                         [texts[0], ''])

    def test_absent_descriptions_leave_reference_completion_to_worker(self):
        self.assertEqual(self.submit().status_code, 202)
        self.assertEqual(self.dispatch.call_args.args[2]['recipe']['reference_descriptions'], [''])

    def test_description_alias_and_invalid_payloads_never_silently_drop_text(self):
        response = self.submit(data={'character_description': '  legacy text  '})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.dispatch.call_args.args[2]['recipe']['reference_descriptions'],
                         ['  legacy text  '])
        for data in ({'character_descriptions': ['first', 'orphan']},
                     {'character_descriptions': ['first', 'second', 'third']},
                     {'character_description': 'legacy', 'character_descriptions': 'canonical'},
                     {'character_description': 'x' * 2001},
                     {'character_descriptions': 'x' * 2001}):
            with self.subTest(fields=list(data)):
                self.dispatch.reset_mock()
                response = self.submit(data=data)
                self.assertEqual(response.status_code, 422, response.text)
                self.dispatch.assert_not_called()

    def test_reference_capacity_and_seed_bounds_are_rejected(self):
        files = [('video', ('source.mp4', b'video', 'video/mp4'))]
        files += [('reference_images', (f'{index}.png', b'image', 'image/png'))
                  for index in range(REFERENCE_SLOTS + 1)]
        response = self.client.post('/api/h3/jobs', files=files)
        self.assertEqual(response.status_code, 422)
        for seed in ('-1', str(2**64)):
            self.assertEqual(self.submit(data={'seed': seed}).status_code, 422)
        self.dispatch.assert_not_called()

    def test_readiness_is_injected_and_no_dispatch_when_blocked(self):
        self.ready.return_value = {'ready': False, 'issues': ['H3 weights missing']}
        self.assertEqual(self.submit().status_code, 503)
        self.dispatch.assert_not_called()
        self.assertFalse(list(self.media.iterdir()))

    def test_single_shot_limit_documented_without_false_positive_cut_gate(self):
        response = self.submit()
        self.assertEqual(response.status_code, 202)
        self.assertIn('One continuous shot', response.text)
        job = self.dispatch.call_args.args[0]
        self.assertEqual(job.meta['source_shot_plan'], [{'start': 0, 'end': 23, 'fps': 24}])
        schema = self.client.get('/openapi.json').json()
        self.assertIn('Multi-cut editing is not', schema['paths']['/api/h3/jobs']['post']['description'])

    def test_replay_uses_frozen_recipe_and_no_inherited_success(self):
        self.submit(data={'character_descriptions': '  frozen character\n'})
        job, source, opts = self.dispatch.call_args.args
        recipe = bind_frames(opts['recipe'], 24)
        result = self.media / 'result.mp4'
        result.write_bytes(b'result')
        freeze_capsule(job, recipe, source, opts['reference_images'], result, self.media)
        job.status, job.result = 'done', str(result)
        job.save()
        response = self.client.get(f'/api/h3/jobs/{job.id}/capsule')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(str(self.root), response.text)
        frozen = copy.deepcopy(core.Job.load(job.id).meta)
        self.assertEqual(self.submit(data={'character_description': 'new draft'}).status_code, 202)
        self.assertEqual(core.Job.load(job.id).meta, frozen, 'A new draft cannot rewrite a frozen take')
        self.dispatch.reset_mock()
        replay = self.client.post(f'/api/h3/jobs/{job.id}/replay')
        self.assertEqual(replay.status_code, 202, replay.text)
        child, replay_source, replay_opts = self.dispatch.call_args.args
        self.assertEqual(replay_opts['recipe'], recipe)
        self.assertEqual(replay_source, source)
        self.assertEqual(child.meta['parent_job_id'], job.id)
        self.assertEqual(child.status, 'queued')
        self.assertIsNone(child.result)
        self.assertNotIn('h3_capsule', child.meta)
        Path(opts['reference_images'][0]).write_bytes(b'changed')
        self.assertEqual(self.client.post(f'/api/h3/jobs/{job.id}/replay').status_code, 409)

    def test_long_source_requires_explicit_selection_before_draft_or_dispatch(self):
        self.source_info.update(frames=528, duration=22)
        async def save(video, destination, limit):
            destination.write_bytes(await video.read())
            return {'frames': 528, 'fps': 24, 'duration': 22, 'width': 64, 'height': 64}
        with patch.object(h3_api, 'save_video', side_effect=save), \
                patch.object(h3_api, 'submission_project', wraps=h3_api.submission_project) as project:
            response = self.submit()
        self.assertEqual(response.status_code, 422, response.text)
        self.dispatch.assert_not_called()
        project.assert_not_called()
        self.assertEqual(core.Job.all(), [])
        self.assertFalse(list(self.media.iterdir()))

    def test_invalid_excerpt_ranges_never_dispatch_or_create_draft(self):
        self.source_info.update(frames=528, duration=22)
        ranges = [({'clip_start_seconds': '2'}), ({'clip_end_seconds': '5'}),
                  {'clip_start_seconds': '', 'clip_end_seconds': ''},
                  {'clip_start_seconds': '', 'clip_end_seconds': '5'},
                  {'clip_start_seconds': '2', 'clip_end_seconds': ''},
                  {'clip_start_seconds': 'NaN', 'clip_end_seconds': '5'},
                  {'clip_start_seconds': '2', 'clip_end_seconds': 'inf'},
                  {'clip_start_seconds': '-1', 'clip_end_seconds': '5'},
                  {'clip_start_seconds': '5', 'clip_end_seconds': '5'},
                  {'clip_start_seconds': '5', 'clip_end_seconds': '2'},
                  {'clip_start_seconds': '2', 'clip_end_seconds': '23'},
                  {'clip_start_seconds': '2', 'clip_end_seconds': '17.01'}]
        for data in ranges:
            with self.subTest(data=data), \
                    patch.object(h3_api, 'submission_project') as project, \
                    patch.object(h3_api, 'extract_excerpt') as extract:
                self.assertEqual(self.submit(data=data).status_code, 422)
                self.dispatch.assert_not_called()
                project.assert_not_called()
                extract.assert_not_called()
                self.assertEqual(core.Job.all(), [])
                self.assertFalse(list(self.media.iterdir()))

    def test_invalid_reference_does_not_create_draft(self):
        with patch.object(h3_api, 'submission_project') as project:
            self.assertEqual(self.submit(b'invalid').status_code, 422)
            project.assert_not_called()

    def test_cleanup_never_unlinks_historical_colliding_paths(self):
        for suffix in ('source.mp4', 'reference-1.png', 'reference-1.upload', 'excerpt.mp4'):
            with self.subTest(suffix=suffix):
                path = self.media / f'fixed-{suffix}'
                path.write_bytes(b'historical')
                with patch.object(h3_api.uuid, 'uuid4', return_value=MagicMock(hex='fixed')), \
                        patch.object(h3_api, 'submission_project') as project:
                    response = self.submit(data={'clip_start_seconds': '0', 'clip_end_seconds': '1'})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(path.read_bytes(), b'historical')
                self.dispatch.assert_not_called()
                project.assert_not_called()
                self.assertEqual(list(self.media.iterdir()), [path])
                path.unlink()  # Test-owned fixture only.

    def test_explicit_project_rejected_before_upload_io(self):
        with patch.object(h3_api, 'save_video') as save:
            self.assertEqual(self.submit(data={'project_id': '../invalid'}).status_code, 422)
            save.assert_not_called()

    def test_readiness_preserves_other_fields_and_limits(self):
        self.ready.return_value = {'ready': True, 'issues': [], 'models': ['h3'],
                                   'limits': {'references': 2}}
        report = self.client.get('/api/h3/readiness').json()
        self.assertEqual(report['models'], ['h3'])
        self.assertEqual(report['limits'], {'references': 2, 'max_clip_seconds': 15})
        self.assertNotIn('max_clip_seconds', self.ready.return_value['limits'])

    def test_dispatch_failure_is_terminal(self):
        self.dispatch.side_effect = RuntimeError('executor unavailable')
        self.assertEqual(self.submit().status_code, 503)
        saved = core.Job.all()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].status, 'error')
        self.assertIsNotNone(saved[0].finished)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class RealSelectionAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory()
        cls.fixture_root = Path(cls.fixtures.name)
        cls.source = cls.fixture_root / 'long.mp4'
        cls.reference = cls.fixture_root / 'ref.png'
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=96x64:r=24:d=22',
               '-f', 'lavfi', '-i', 'sine=frequency=440:duration=22',
               '-c:v', 'libx264', '-c:a', 'aac', cls.source)
        ffmpeg('-f', 'lavfi', '-i', 'color=red:s=64x64', '-frames:v', 1,
               '-threads', 1, cls.reference)

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'media'
        self.media.mkdir()
        self.work_patch = patch.object(core, 'WORK', self.root)
        self.work_patch.start()
        self.addCleanup(self.work_patch.stop)
        self.dispatch = MagicMock()
        app = FastAPI()
        app.include_router(h3_api.create_router(lambda: self.media, 2*1024*1024,
                                               lambda: {'ready': True}, self.dispatch))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def submit(self, **kwargs):
        return self.client.post('/api/h3/jobs', files={
            'video': ('source.mp4', self.source.read_bytes(), 'video/mp4'),
            'reference_images': ('ref.png', self.reference.read_bytes(), 'image/png')}, **kwargs)

    def test_real_long_source_is_422_without_draft_job_or_gpu(self):
        with patch.object(h3_api, 'submission_project') as project, \
                patch.object(h3_pipeline, 'make_client') as sdk:
            response = self.submit()
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('explicit excerpt', response.text)
        self.dispatch.assert_not_called()
        project.assert_not_called()
        sdk.assert_not_called()
        self.assertEqual(core.Job.all(), [])
        self.assertFalse(list(self.media.iterdir()))

    def test_real_selected_source_retains_original_and_replays_exact_excerpt(self):
        response = self.submit(data={'clip_start_seconds': '2', 'clip_end_seconds': '5',
                                     'character_description': '  unchanged text\n',
                                     'seed': str(2**64-1)})
        self.assertEqual(response.status_code, 202, response.text)
        job, source, opts = self.dispatch.call_args.args
        original = Path(job.meta['h3_original_source'])
        self.assertNotEqual(source, original)
        self.assertEqual(digest_file(original), digest_file(self.source))
        self.assertEqual(job.video, str(source))
        self.assertEqual(job.meta['source_info']['duration'], 3)
        self.assertEqual(job.meta['source_shot_plan'], [{'start': 0, 'end': 71, 'fps': 24}])
        self.assertEqual(opts['recipe']['seed'], 2**64-1)
        self.assertEqual(opts['recipe']['reference_descriptions'], ['  unchanged text\n'])
        selection = opts['recipe']['source_selection']
        self.assertEqual(set(selection), {'schema_version', 'start_seconds', 'end_seconds',
                                         'original_duration_seconds', 'original_sha256', 'original_size_bytes'})
        self.assertEqual((selection['start_seconds'], selection['end_seconds']), (2, 5))
        self.assertEqual(selection['original_sha256'], digest_file(original))
        self.assertEqual(selection['original_size_bytes'], original.stat().st_size)
        self.assertNotIn(str(self.root), response.text)
        # Seal a real input without pretending a model has rendered anything.
        result = self.media / 'capsule-test-result.mp4'
        result.write_bytes(b'unit-test-result-not-a-render')
        recipe = bind_frames(opts['recipe'], 72, source_audio=True)
        frozen = freeze_capsule(job, recipe, source, opts['reference_images'], result, self.media)
        job.result, job.status = str(result), 'done'
        job.save()
        self.assertEqual(frozen['assets']['source']['sha256'], digest_file(source))
        self.assertNotEqual(frozen['assets']['source']['sha256'], digest_file(original))
        capsule = self.client.get(f'/api/h3/jobs/{job.id}/capsule')
        self.assertEqual(capsule.status_code, 200)
        self.assertNotIn(str(self.root), capsule.text)
        self.assertEqual(capsule.json()['recipe']['source_selection'], selection)
        saved = copy.deepcopy(core.Job.load(job.id).meta)
        with patch.object(h3_api, 'extract_excerpt', side_effect=AssertionError('replay must not trim')):
            replay = self.client.post(f'/api/h3/jobs/{job.id}/replay')
        self.assertEqual(replay.status_code, 202, replay.text)
        child, replay_source, replay_opts = self.dispatch.call_args.args
        self.assertEqual(replay_source, source)
        self.assertEqual(replay_opts['recipe'], recipe)
        self.assertEqual(child.meta['h3_original_source'], str(original))
        self.assertEqual(core.Job.load(job.id).meta, saved)
        self.assertEqual(digest_file(original), digest_file(self.source))
        self.dispatch.reset_mock()
        source.write_bytes(b'changed')
        self.assertEqual(self.client.post(f'/api/h3/jobs/{job.id}/replay').status_code, 409)
        self.dispatch.assert_not_called()

    def test_real_15_second_boundary_is_allowed_but_15_01_is_not(self):
        with patch.object(h3_api, 'submission_project') as project, \
                patch.object(h3_api, 'extract_excerpt') as encoder:
            response = self.submit(data={'clip_start_seconds': '2', 'clip_end_seconds': '17.01'})
        self.assertEqual(response.status_code, 422, response.text)
        project.assert_not_called()
        encoder.assert_not_called()
        self.dispatch.assert_not_called()
        self.assertFalse(list(self.media.iterdir()))
        response = self.submit(data={'clip_start_seconds': '2', 'clip_end_seconds': '17'})
        self.assertEqual(response.status_code, 202, response.text)
        job, _, _ = self.dispatch.call_args.args
        self.assertEqual(job.meta['source_info']['duration'], 15)

    def test_historical_long_assets_stay_readable_but_replay_is_refused(self):
        source = self.media / 'historical.mp4'
        shutil.copyfile(self.source, source)
        reference = self.media / 'historical.png'
        shutil.copyfile(self.reference, reference)
        result = self.media / 'historical-result.mp4'
        result.write_bytes(b'historical-result')
        recipe = bind_frames(h3_api.make_recipe(source_width=96, source_height=64), 528, source_audio=True)
        parent = core.Job('historical-h3', engine='minimax-h3', video=str(source),
                          meta={'h3_references': [str(reference)]})
        freeze_capsule(parent, recipe, source, [reference], result, self.media)
        parent.status, parent.result = 'done', str(result)
        parent.save()
        frozen = copy.deepcopy(parent.meta)
        with patch.object(h3_api, 'submission_project') as project:
            self.assertEqual(self.client.get(f'/api/h3/jobs/{parent.id}/capsule').status_code, 200)
            self.assertEqual(self.client.get(f'/api/h3/jobs/{parent.id}/source').status_code, 200)
            self.assertEqual(self.client.post(f'/api/h3/jobs/{parent.id}/replay').status_code, 409)
            project.assert_not_called()
        self.dispatch.assert_not_called()
        self.assertEqual(core.Job.load(parent.id).meta, frozen)
        self.assertEqual(len(core.Job.all()), 1)


if __name__ == '__main__':
    unittest.main()