"""Genuine CPU FFmpeg evidence: nonzero selection, A/V sync and immutable original."""
import array
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from h3_capsule import digest_file
from h3_media import ffmpeg
import source_clip as clip


def synthetic_source(destination, duration=22, rate='24', size='96x64'):
    # Continuous luminance motion plus a visible AND audible boundary at 3.5 s.
    ffmpeg('-f', 'lavfi', '-i', f'nullsrc=s={size}:r={rate}:d={duration}',
           '-f', 'lavfi', '-i',
           f'aevalsrc=0.3*sin(2*PI*if(lt(t\\,3.5)\\,330\\,880)*t):s=48000:d={duration}',
           '-vf', "geq=lum='if(lt(T,3.5),40+10*T,140+2*T)':cb=128:cr=128",
           '-t', duration, '-c:v', 'libx264', '-crf', 12, '-c:a', 'aac', destination)


def video_pixels(path):
    return subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0',
                           '-pix_fmt', 'gray', '-f', 'rawvideo', '-'],
                          check=True, capture_output=True, timeout=60).stdout


def audio_samples(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0',
                          '-ar', '48000', '-ac', '1', '-f', 'f32le', '-'],
                         check=True, capture_output=True, timeout=60).stdout
    values = array.array('f')
    values.frombytes(raw)
    return values


class SelectionTests(unittest.TestCase):
    def test_bounds_and_no_implicit_trim(self):
        self.assertEqual(clip.validate_selection({'duration': 15}), (0, 15))
        self.assertEqual(clip.validate_selection({'duration': 22}, 2, 5), (2, 5))
        self.assertEqual(clip.validate_selection({'duration': 22}, 2, 17), (2, 17))
        for bounds in [(None, None), (2, None), (None, 5), (math.nan, 5),
                       (2, math.inf), (-1, 5), (5, 5), (5, 2), (2, 23), (2, 17.01)]:
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                clip.validate_selection({'duration': 22}, *bounds)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class CPUExcerptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.source = cls.root / 'original.mp4'
        synthetic_source(cls.source)
        cls.info = clip.probe_source(cls.source)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_nonzero_excerpt_content_and_audio_share_the_selected_interval(self):
        before = digest_file(self.source)
        destination = self.root / 'selected.mp4'
        info, selection = clip.extract_excerpt(self.source, destination, self.info, 2, 5)
        self.assertEqual(digest_file(self.source), before)
        self.assertEqual((info['width'], info['height'], info['frames'], info['fps'], info['duration']),
                         (96, 64, 72, 24, 3))
        self.assertEqual(selection, {'schema_version': 1, 'start_seconds': 2., 'end_seconds': 5.,
                                    'original_duration_seconds': 22., 'original_sha256': before,
                                    'original_size_bytes': self.source.stat().st_size})
        self.assertNotIn(str(self.root), json.dumps(selection))
        source_pixels, selected_pixels = video_pixels(self.source), video_pixels(destination)
        frame_size = 96 * 64
        # Comparing multiple individual frames proves the nonzero offset, not just a cut.
        for index in (0, 12, 35, 36, 60, 71):
            src = source_pixels[(48+index)*frame_size:(49+index)*frame_size]
            dst = selected_pixels[index*frame_size:(index+1)*frame_size]
            self.assertLess(sum(abs(a-b) for a, b in zip(src, dst)) / frame_size, 3)
        self.assertGreater(abs(source_pixels[0] - selected_pixels[0]), 15)
        samples = audio_samples(destination)
        self.assertGreaterEqual(len(samples), 3 * 48000)
        def frequency(start, end):
            values = samples[int(start*48000):int(end*48000)]
            crossings = sum(a <= 0 < b for a, b in zip(values, values[1:]))
            return crossings / (end-start)
        # Original change at 3.5 s must be at 1.5 s in both tracks after selecting [2,5].
        self.assertAlmostEqual(frequency(.2, 1.4), 330, delta=3)
        self.assertAlmostEqual(frequency(1.6, 2.8), 880, delta=3)
        means = [sum(selected_pixels[i*frame_size:(i+1)*frame_size]) / frame_size
                 for i in range(72)]
        video_boundary = max(range(1, 72), key=lambda i: means[i]-means[i-1]) / 24
        audio_boundary = next(t/100 for t in range(120, 180)
                              if frequency(t/100, t/100+.05) > 650)
        self.assertAlmostEqual(video_boundary, 1.5, delta=1/24)
        self.assertAlmostEqual(audio_boundary, video_boundary, delta=.06)
        starts = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                 'stream=start_time', '-of', 'json', str(destination)],
                                check=True, text=True, capture_output=True).stdout
        self.assertTrue(all(abs(float(s['start_time'])) < 1/24 for s in json.loads(starts)['streams']))

    def test_whole_source_guard_is_cpu_only_and_never_trims(self):
        before = digest_file(self.source)
        with patch.object(clip, 'ffmpeg') as encoder, self.assertRaises(ValueError):
            clip.require_short_source(self.source)
        encoder.assert_not_called()
        self.assertEqual(digest_file(self.source), before)

    def test_video_duration_ignores_longer_audio(self):
        destination = self.root / 'long-audio.mp4'
        ffmpeg('-f', 'lavfi', '-i', 'color=red:s=64x64:r=24:d=15',
               '-f', 'lavfi', '-i', 'sine=frequency=440:duration=16',
               '-c:v', 'libx264', '-c:a', 'aac', destination)
        self.assertEqual(clip.require_short_source(destination)['duration'], 15)

    def test_fractional_rate_and_odd_dimensions_preserve_geometry(self):
        source, destination = self.root / 'odd.mp4', self.root / 'odd-excerpt.mp4'
        ffmpeg('-f', 'lavfi', '-i', 'testsrc=s=129x97:r=30000/1001:d=5',
               '-c:v', 'libx264', '-pix_fmt', 'yuv444p', source)
        info, _ = clip.extract_excerpt(source, destination, clip.probe_source(source), 1.001, 3.003)
        self.assertEqual((info['width'], info['height'], info['frames']), (129, 97, 60))
        self.assertAlmostEqual(info['fps'], 30000/1001, places=4)
        self.assertLess(info['duration'], 2.04)

    def test_relative_stream_delay_is_not_erased_by_independent_pts_reset(self):
        source, destination = self.root / 'delayed.mp4', self.root / 'delayed-excerpt.mp4'
        # Audio starts 2 s after video. Selecting [1,4] must leave 1 s of silence,
        # not shift the tone to excerpt t=0 by resetting each stream separately.
        ffmpeg('-f', 'lavfi', '-i', 'color=red:s=64x64:r=24:d=5',
               '-itsoffset', 2, '-f', 'lavfi', '-i', 'sine=frequency=880:duration=3',
               '-c:v', 'libx264', '-c:a', 'aac', source)
        clip.extract_excerpt(source, destination, clip.probe_source(source), 1, 4)
        values = audio_samples(destination)
        def energy(start, end):
            data = values[int(start*48000):int(end*48000)]
            return sum(v*v for v in data) / len(data)
        self.assertLess(energy(.2, .8), 1e-6)
        self.assertGreater(energy(1.2, 1.8), .001)

    def test_existing_destination_is_never_overwritten_or_unlinked(self):
        destination = self.root / 'existing.mp4'
        destination.write_bytes(b'historical')
        with self.assertRaises(ValueError):
            clip.extract_excerpt(self.source, destination, self.info, 2, 5)
        self.assertEqual(destination.read_bytes(), b'historical')

    def test_failed_extraction_only_cleans_its_new_output(self):
        destination = self.root / 'failed.mp4'
        def fail(*args):
            destination.write_bytes(b'partial')
            raise RuntimeError('encoder failure')
        with patch.object(clip, 'ffmpeg', side_effect=fail), self.assertRaises(RuntimeError):
            clip.extract_excerpt(self.source, destination, self.info, 2, 5)
        self.assertFalse(destination.exists())
        self.assertTrue(self.source.exists())


if __name__ == '__main__':
    unittest.main()
