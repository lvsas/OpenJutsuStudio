"""Real FFmpeg verification: frame grid, silent/audio source, image byte bounds."""
import asyncio
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from fastapi import HTTPException, UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from h3_media import ffmpeg, prepare_source, finish_result, validate_result
from h3_uploads import save_reference
from media import ffprobe


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def audio_streams(self, path):
        result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a',
                                 '-show_entries', 'stream=codec_name', '-of', 'json', str(path)],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)['streams']

    def test_non24fps_normalized_padded_trimmed_silent_and_audio(self):
        # The winning A/B arm conditions on the source soundtrack, so the prepared
        # clip keeps it and the render returns it; local muxing is fallback only.
        for audio in (False, True):
            with self.subTest(audio=audio):
                folder = self.root / str(audio)
                folder.mkdir()
                source = folder / 'source.mp4'
                args = ['-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=30:duration=1']
                if audio:
                    args += ['-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:a', 'aac']
                ffmpeg(*args, '-c:v', 'libx264', source)
                padded, count, length = prepare_source(source, folder)
                self.assertEqual((count, length), (24, 39))
                self.assertEqual(ffprobe(padded)['frames'], 39)
                self.assertEqual(bool(self.audio_streams(padded)), audio)
                result = finish_result(padded, source, folder / 'result.mp4', count)
                validate_result(result, 24, 64, 64)
                self.assertEqual(bool(self.audio_streams(result)), audio)
                if audio:
                    pcm = []
                    for path in (source, result):
                        output = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path),
                                                 '-f', 's16le', '-ac', '1', '-ar', '24000', '-'],
                                                capture_output=True, check=True).stdout
                        import array
                        samples = array.array('h')
                        samples.frombytes(output)
                        pcm.append(samples)
                    n = min(map(len, pcm))
                    a, b = pcm[0][:n], pcm[1][:n]
                    corr = sum(x*y for x, y in zip(a, b)) / (
                        sum(x*x for x in a) * sum(y*y for y in b)) ** 0.5
                    self.assertGreater(corr, 0.98)

    def test_reference_decoded_reencoded_and_invalid_bounded(self):
        image = self.root / 'source.png'
        ffmpeg('-f', 'lavfi', '-i', 'color=blue:size=64x64', '-frames:v', 1,
               '-threads', 1, image)
        destination = self.root / 'reference.png'
        upload = UploadFile(filename='reference.png', file=io.BytesIO(image.read_bytes()))
        asyncio.run(save_reference(upload, destination, 4096))
        self.assertEqual(ffprobe(destination)['width'], 64)
        for content, limit, expected in [(b'not-an-image', 4096, 422), (b'x'*20, 10, 413),
                                          (b'', 4096, 422)]:
            upload = UploadFile(filename='reference.png', file=io.BytesIO(content))
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(save_reference(upload, destination, limit))
            self.assertEqual(raised.exception.status_code, expected)
            self.assertFalse(destination.exists())
            self.assertFalse(list(self.root.glob('*.upload')))

    def test_frame_grid_padding_clones_final_frame(self):
        source = self.root / 'source.mp4'
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=24:duration=0.5',
               '-c:v', 'libx264', source)
        padded, count, length = prepare_source(source, self.root)
        self.assertEqual((count, length), (12, 22))
        def pixels(index):
            return subprocess.run(['ffmpeg', '-v', 'error', '-i', str(padded),
                                   '-vf', f'select=eq(n\\,{index})', '-frames:v', '1',
                                   '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                  capture_output=True, check=True).stdout
        first, last = pixels(11), pixels(21)
        # Lossy H264 may alter clone reconstruction slightly, not replace content.
        self.assertLess(sum(abs(a-b) for a, b in zip(first, last))/len(first), 3)


if __name__ == '__main__':
    unittest.main()
