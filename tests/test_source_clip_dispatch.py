"""Real multipart -> real FFmpeg -> dispatched file; only GPU execution is mocked."""
import hashlib
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import core
from h3_api import create_router as h3_router
from h3_media import ffmpeg
from job_api import create_router as ltx_router
from source_clip import probe_source


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class RealDispatchTests(unittest.TestCase):
    def test_both_studios_dispatch_the_physical_excerpt_not_the_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'offset-original.mp4'
            ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=96x64:r=24:d=8',
                   '-f', 'lavfi', '-i', 'sine=frequency=880:duration=8',
                   '-c:v', 'libx264', '-c:a', 'aac', '-output_ts_offset', 7, original)
            original_bytes = original.read_bytes()
            self.assertAlmostEqual(probe_source(original)['video_start_seconds'], 7)
            image = io.BytesIO()
            Image.new('RGB', (64, 64), (100, 80, 60)).save(image, format='PNG')
            for engine, route, factory in [('ltx', '/api/jobs', ltx_router),
                                            ('h3', '/api/h3/jobs', h3_router)]:
                with self.subTest(engine=engine), patch.object(core, 'WORK', root / engine):
                    media = root / engine / 'media'
                    media.mkdir(parents=True)
                    dispatch = MagicMock()
                    ready = lambda: {'ready': True, 'issues': []}
                    args = (lambda: media, 10_000_000, ready, dispatch)
                    app = FastAPI()
                    app.include_router(factory(*args, *(['ltx25-ripple'] if engine == 'ltx' else [])))
                    with TestClient(app) as client:
                        response = client.post(route, data={
                            'edit_prompt': 'Keep the scene',
                            'clip_start_seconds': '2', 'clip_end_seconds': '5'}, files=[
                                ('video', ('offset.mp4', original_bytes, 'video/mp4')),
                                ('reference_images', ('one.png', image.getvalue(), 'image/png')),
                                ('reference_images', ('two.png', image.getvalue(), 'image/png'))])
                    self.assertEqual(response.status_code, 202, response.text)
                    job, selected, opts = dispatch.call_args.args
                    self.assertEqual(Path(job.video), selected)
                    self.assertTrue(selected.name.endswith('-excerpt.mp4'))
                    measured = probe_source(selected)
                    self.assertEqual((measured['frames'], measured['fps'], measured['duration']), (72, 24, 3))
                    self.assertAlmostEqual(measured['video_start_seconds'], 0)
                    original_key = 'original_source' if engine == 'ltx' else 'h3_original_source'
                    saved_original = Path(job.meta[original_key])
                    self.assertNotEqual(saved_original, selected)
                    self.assertEqual(saved_original.read_bytes(), original_bytes)
                    recipe = job.meta['take_recipe' if engine == 'ltx' else 'h3_recipe']
                    self.assertEqual(recipe['source_selection']['start_seconds'], 2)
                    self.assertEqual(recipe['source_selection']['original_sha256'],
                                     hashlib.sha256(original_bytes).hexdigest())
                    self.assertEqual(core.Job.load(job.id).video, str(selected))
                    if engine == 'ltx':
                        self.assertEqual(opts['propagate']['frames'], 72)
                    else:
                        self.assertEqual(opts['recipe']['source_timing']['frames'], 72)


if __name__ == '__main__':
    unittest.main()
