"""LTX excerpt contracts: no GPU, no live workspace, shared CPU extraction policy."""
import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import core
import job_api
from api_schema import _public_job


class LTXClipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'media'
        self.info = {'duration': 22., 'frames': 528, 'fps': 24., 'width': 64, 'height': 64}
        self.dispatch = MagicMock()
        self.ready = MagicMock(return_value={'ready': True, 'issues': []})
        self.addCleanup(patch.stopall)
        patch.object(core, 'WORK', self.root).start()
        async def save(upload, destination, limit):
            destination.write_bytes(await upload.read())
            return copy.deepcopy(self.info)
        patch.object(job_api, 'save_video', side_effect=save).start()
        patch.object(job_api, 'probe_source', side_effect=lambda path: copy.deepcopy(self.info)).start()
        app = FastAPI()
        app.include_router(job_api.create_router(lambda: self.media, 4096, self.ready,
                                                 self.dispatch, 'ltx25-ripple'))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def submit(self, **data):
        return self.client.post('/api/jobs', files={'video': ('source.mp4', b'original bytes', 'video/mp4')},
                                data={'edit_prompt': 'Keep the scene; change the character', **data})

    def test_long_source_is_refused_without_job_or_lazy_draft(self):
        response = self.submit()
        self.assertEqual(response.status_code, 422, response.text)
        self.dispatch.assert_not_called()
        self.assertFalse(list(self.root.rglob('*.json')))

    def test_short_whole_source_keeps_original_contract(self):
        self.info.update(duration=8., frames=192)
        response = self.submit()
        self.assertEqual(response.status_code, 202, response.text)
        job, source, opts = self.dispatch.call_args.args
        self.assertEqual(source.read_bytes(), b'original bytes')
        self.assertEqual(opts['propagate']['frames'], 192)
        self.assertNotIn('source_selection', job.meta['take_recipe'])

    def test_explicit_selection_freezes_excerpt_before_dispatch(self):
        def extract(source, destination, info, start, end, **kwargs):
            destination.write_bytes(b'chosen excerpt')
            return ({**info, 'duration': end-start, 'frames': int((end-start)*24)},
                    {'schema_version': 1, 'start_seconds': start, 'end_seconds': end,
                     'original_duration_seconds': info['duration'],
                     'original_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                     'original_size_bytes': source.stat().st_size})
        with patch.object(job_api, 'extract_excerpt', side_effect=extract) as extraction:
            response = self.submit(clip_start_seconds='2', clip_end_seconds='5')
        self.assertEqual(response.status_code, 202, response.text)
        job, source, opts = self.dispatch.call_args.args
        self.assertEqual(source.read_bytes(), b'chosen excerpt')
        self.assertEqual(opts['propagate']['frames'], 72)
        self.assertEqual(Path(job.meta['original_source']).read_bytes(), b'original bytes')
        self.assertEqual(job.meta['take_recipe']['source_selection']['start_seconds'], 2.)
        self.assertEqual(core.Job.load(job.id).meta['take_recipe'], job.meta['take_recipe'])
        self.assertNotIn(str(self.root), str(response.json()['job']['meta'].get('original_source', '')))
        self.assertNotIn('original_source', response.json()['job']['meta'])
        extraction.assert_called_once()

    def test_invalid_ranges_never_dispatch(self):
        for values in ({'clip_start_seconds': '2'}, {'clip_end_seconds': '5'},
                       {'clip_start_seconds': '', 'clip_end_seconds': ''},
                       {'clip_start_seconds': 'nan', 'clip_end_seconds': '5'},
                       {'clip_start_seconds': '0', 'clip_end_seconds': 'inf'},
                       {'clip_start_seconds': '-1', 'clip_end_seconds': '5'},
                       {'clip_start_seconds': '5', 'clip_end_seconds': '2'},
                       {'clip_start_seconds': '0', 'clip_end_seconds': '15.01'},
                       {'clip_start_seconds': '20', 'clip_end_seconds': '25'}):
            with self.subTest(values=values):
                response = self.submit(**values)
                self.assertEqual(response.status_code, 422, response.text)
                self.dispatch.assert_not_called()
        self.assertFalse(list(self.root.rglob('*.json')))

    def test_long_legacy_replay_is_refused_without_changing_saved_input(self):
        from fastapi import HTTPException
        from take_capsule_api import _replay_inputs
        source = self.media / 'legacy.mp4'
        self.media.mkdir(exist_ok=True)
        source.write_bytes(b'legacy source')
        parent = core.Job(id='b'*32, video=str(source), meta={
            'take_recipe': {'schema_version': 1, 'frames': 528, 'fps': 24},
            'shots': [{'start': 0, 'end': 527}]})
        with self.assertRaises(HTTPException) as refusal:
            _replay_inputs(parent)
        self.assertEqual(refusal.exception.status_code, 409)
        self.assertEqual(source.read_bytes(), b'legacy source')
        self.dispatch.assert_not_called()

    def test_private_original_paths_are_not_serialized_or_mutated(self):
        meta = {'original_source': '/private/original.mp4',
                'h3_original_source': '/private/h3-original.mp4', 'other': 1}
        job = core.Job(id='a'*32, meta=copy.deepcopy(meta))
        self.assertEqual(_public_job(job)['meta'], {'other': 1})
        self.assertEqual(job.meta, meta)


if __name__ == '__main__':
    unittest.main()
