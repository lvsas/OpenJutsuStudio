"""CPU-only disposable fixtures; no real jobs, media, SDK or GPU submissions."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from swap_preview import prepare_poster, PreviewUnavailable, _SLOTS
from job_api import create_poster_router


class SwapPosterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = self.root / 'downloaded-result.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=teal:size=640x360:rate=24:duration=0.2',
                        '-threads', '1', '-c:v', 'libx264', str(self.video)], check=True)

    def test_cpu_jpeg_aspect_cache_and_source_invalidation(self):
        original = self.video.read_bytes()
        poster = prepare_poster(self.root, self.video)
        self.assertTrue(poster.read_bytes().startswith(b'\xff\xd8'))
        info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                                  '-of', 'json', str(poster)]))['streams'][0]
        self.assertEqual((info['codec_name'], info['width'], info['height']), ('mjpeg', 320, 180))
        with patch('swap_preview.subprocess.run', side_effect=AssertionError('cache re-encoded')):
            self.assertEqual(prepare_poster(self.root, self.video), poster)
        self.assertEqual(self.video.read_bytes(), original)
        stat = self.video.stat()
        os.utime(self.video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
        self.assertNotEqual(prepare_poster(self.root, self.video), poster)
        self.assertEqual(self.video.read_bytes(), original)

    def test_failure_is_path_free_and_atomic(self):
        self.video.write_bytes(b'not a video')
        with self.assertRaises(PreviewUnavailable) as error:
            prepare_poster(self.root, self.video)
        self.assertNotIn(str(self.root), str(error.exception))
        cache = self.root / 'timeline' / 'previews' / 'swap-poster-jpeg-v1'
        self.assertEqual(list(cache.iterdir()), [])

    def test_timeout_and_bounded_concurrency(self):
        with patch('swap_preview.subprocess.run', side_effect=subprocess.TimeoutExpired('ffmpeg', 20)) as run:
            with self.assertRaises(PreviewUnavailable):
                prepare_poster(self.root, self.video)
            args, kwargs = run.call_args
            self.assertEqual(kwargs['timeout'], 20)
            self.assertNotIn('-hwaccel', args[0])
            self.assertIn('-threads', args[0])
        with patch('swap_preview._SLOTS') as slots:
            slots.acquire.return_value=False
            with self.assertRaises(PreviewUnavailable):
                prepare_poster(self.root,self.video)
            slots.acquire.assert_called_once_with(timeout=20)
            slots.release.assert_not_called()

    def test_cold_cache_burst_waits_for_two_encoder_slots(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import time
        sources=[]
        for index in range(8):
            path=self.root / f'burst-{index}.mp4'
            path.write_bytes(self.video.read_bytes())
            sources.append(path)
        start=threading.Barrier(8)
        real_run=subprocess.run
        guard=threading.Lock()
        active=peak=0
        def encode(*args, **kwargs):
            nonlocal active, peak
            with guard:
                active+=1
                peak=max(peak,active)
            try:
                time.sleep(.1)
                return real_run(*args, **kwargs)
            finally:
                with guard:active-=1
        def request(path):
            start.wait(timeout=5)
            return prepare_poster(self.root,path)
        with patch('swap_preview.subprocess.run',side_effect=encode), ThreadPoolExecutor(max_workers=8) as pool:
            posters=list(pool.map(request,sources))
        self.assertEqual(len(posters),8)
        self.assertTrue(all(path.is_file() for path in posters))
        self.assertLessEqual(peak,2)

    def test_symlinks_and_corrupt_cache_fail_closed(self):
        link = self.root / 'link.mp4'
        link.symlink_to(self.video)
        with self.assertRaises(PreviewUnavailable):
            prepare_poster(self.root, link)
        poster = prepare_poster(self.root, self.video)
        poster.write_bytes(b'corrupt')
        with self.assertRaises(PreviewUnavailable):
            prepare_poster(self.root, self.video)

    def test_route_reuses_confined_media_validator(self):
        import app as original
        import core
        from timeline_store import TimelineStore
        media = self.root / 'media'
        media.mkdir()
        with patch.object(core, 'WORK', self.root):
            core.Job(id='b' * 32, engine='ltx25-ripple', status='done', result=str(self.video)).save()
            app = FastAPI()
            store = TimelineStore(self.root, media, 500 * 1024 * 1024)
            app.include_router(create_poster_router(original.get_result, lambda: store))
            with TestClient(app) as client, patch('swap_preview.subprocess.run') as encode:
                response = client.get('/api/jobs/' + 'b' * 32 + '/poster')
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn(str(self.root), response.text)
                encode.assert_not_called()

    def test_route_reuses_real_result_validator_mime_and_range(self):
        import app as original
        import core
        self.assertIn('/api/jobs/{job_id}/poster',original.app.openapi()['paths'],
                      'production app must register the poster router')
        with patch.object(core, 'WORK', self.root), patch.object(original, 'MEDIA_DIR', self.root):
            from timeline_store import TimelineStore
            store = TimelineStore(self.root, self.root, 500 * 1024 * 1024)
            core.Job(id='a' * 32, engine='minimax-h3', status='done', result=str(self.video)).save()
            core.Job(id='isolated-pending', status='running', result=str(self.video)).save()
            app = FastAPI()
            app.include_router(create_poster_router(original.get_result, lambda: store))
            with TestClient(app) as client:
                response = client.get('/api/jobs/' + 'a' * 32 + '/poster')
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.headers['content-type'], 'image/jpeg')
                part = client.get('/api/jobs/' + 'a' * 32 + '/poster', headers={'Range': 'bytes=0-15'})
                self.assertEqual(part.status_code, 206)
                self.assertEqual(part.content, response.content[:16])
                self.assertEqual(client.get('/api/jobs/isolated-pending/poster').status_code, 409)
                self.assertEqual(client.get('/api/jobs/missing/poster').status_code, 404)
                self.video.write_bytes(b'broken')
                failure = client.get('/api/jobs/' + 'a' * 32 + '/poster')
                self.assertEqual(failure.status_code, 503)
                self.assertNotIn(str(self.root), failure.text)


if __name__ == '__main__':
    unittest.main()
