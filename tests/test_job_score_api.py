"""The score endpoint must refuse unfinished work and report a measured take."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app as app_module


def make_clip(path: Path, pattern: str, seconds: float) -> Path:
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    f'{pattern}=size=320x180:rate=24:duration={seconds}',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)], check=True)
    return path


class JobScoreApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / 'media').mkdir()
        self.root = root
        self.patches = [patch.object(app_module.core, 'WORK', root),
                        patch.object(app_module, 'MEDIA_DIR', root / 'media')]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(app_module.app)

    def write_job(self, job_id: str, status: str, source: Path | None, result: Path | None):
        job = {'id': job_id, 'status': status, 'engine': 'minimax-h3', 'prompt': '',
               'video': str(source) if source else '',
               'result': str(result) if result else None,
               'created': 0.0, 'progress': 1.0 if status == 'done' else 0.0}
        (self.root / 'jobs').mkdir(exist_ok=True)
        (self.root / 'jobs' / f'{job_id}.json').write_text(json.dumps(job))

    def test_a_finished_swap_is_measured_against_its_source(self):
        job_id = 'a' * 32
        source = make_clip(self.root / 'media' / 'src.mp4', 'testsrc', 2)
        result = make_clip(self.root / 'media' / 'out.mp4', 'testsrc', 2)
        self.write_job(job_id, 'done', source, result)
        body = self.client.get(f'/api/jobs/{job_id}/score').json()
        self.assertEqual(body['job_id'], job_id)
        self.assertEqual(body['score'], 100)
        self.assertEqual(body['flags'], [])

    def test_a_frozen_take_is_reported_as_frozen(self):
        job_id = 'b' * 32
        source = make_clip(self.root / 'media' / 'src2.mp4', 'testsrc', 2)
        result = make_clip(self.root / 'media' / 'out2.mp4', 'color', 2)
        self.write_job(job_id, 'done', source, result)
        body = self.client.get(f'/api/jobs/{job_id}/score').json()
        self.assertIn('frozen', body['flags'])
        self.assertEqual(body['score'], 0)

    def test_unfinished_or_unknown_swaps_are_refused(self):
        job_id = 'c' * 32
        self.write_job(job_id, 'running', None, None)
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}/score').status_code, 409)
        self.assertEqual(self.client.get('/api/jobs/' + 'd' * 32 + '/score').status_code, 404)

    def test_a_missing_clip_is_not_invented(self):
        job_id = 'e' * 32
        source = make_clip(self.root / 'media' / 'src3.mp4', 'testsrc', 1)
        self.write_job(job_id, 'done', source, self.root / 'media' / 'nope.mp4')
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}/score').status_code, 404)


if __name__ == '__main__':
    unittest.main()
