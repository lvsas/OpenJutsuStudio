"""Take scoring: it must catch a frozen take and never invent a verdict."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from take_score import TakeScore, score_take


def clip(path: Path, source: str, seconds: float, extra: list[str] | None = None) -> Path:
    cmd = ['ffmpeg', '-v', 'error', '-y']
    if source == 'testsrc':
        cmd += ['-f', 'lavfi', '-i', f'testsrc=size=320x180:rate=24:duration={seconds}']
    elif source == 'still':
        cmd += ['-f', 'lavfi', '-i', f'color=c=0x3366cc:size=320x180:rate=24:duration={seconds}']
    else:
        cmd += ['-i', source]
    cmd += (extra or []) + ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)]
    subprocess.run(cmd, check=True)
    return path


class TakeScoreRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_take_compared_with_itself_scores_one_hundred(self):
        moving = clip(self.dir / 'moving.mp4', 'testsrc', 3)
        result = score_take(moving, moving)
        self.assertEqual(result.score, 100)
        self.assertEqual(result.flags, ())
        self.assertGreater(result.frames_compared, 10)

    def test_a_frozen_take_is_flagged_and_scores_zero(self):
        moving = clip(self.dir / 'moving.mp4', 'testsrc', 3)
        frozen = clip(self.dir / 'frozen.mp4', 'still', 3)
        result = score_take(moving, frozen)
        self.assertEqual(result.score, 0)
        self.assertIn('frozen', result.flags)
        self.assertLess(result.ratio, 0.15)

    def test_a_still_source_is_reported_instead_of_scored(self):
        still = clip(self.dir / 'still.mp4', 'still', 2)
        moving = clip(self.dir / 'moving.mp4', 'testsrc', 2)
        result = score_take(still, moving)
        self.assertEqual(result.flags, ('source-still',))
        self.assertEqual(result.score, 50)

    def test_a_wildtake_is_flagged(self):
        # same performance, played four times faster: motion energy explodes
        normal = clip(self.dir / 'normal.mp4', 'testsrc', 3)
        fast = clip(self.dir / 'fast.mp4', 'testsrc', 3, ['-vf', 'setpts=0.25*PTS'])
        result = score_take(normal, fast)
        self.assertIn('wild-motion', result.flags)
        self.assertLess(result.score, 50)

    def test_missing_file_is_refused(self):
        moving = clip(self.dir / 'moving.mp4', 'testsrc', 1)
        with self.assertRaises(ValueError):
            score_take(moving, self.dir / 'nope.mp4')

    def test_result_is_json_ready(self):
        moving = clip(self.dir / 'moving.mp4', 'testsrc', 1)
        body = score_take(moving, moving).as_dict()
        self.assertIsInstance(body['flags'], list)
        for key in ('score', 'source_motion', 'result_motion', 'ratio', 'frames_compared'):
            self.assertIn(key, body)


if __name__ == '__main__':
    unittest.main()
