"""The preserved-content description: sampling, contract and graph shape."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from h3_preserve import (FRAME_COUNT, INSTRUCTION, SAVE_NODE, VISION_MODEL, VISION_NODE,
                         _saved_text, build_preserve_graph, frame_indices, sample_frames,
                         validate_preserved)


class FakeOutput:
    def __init__(self, name, content_type, payload):
        self.name, self.content_type, self._payload = name, content_type, payload

    def to_bytes(self):
        return self._payload


class FakeJob:
    def __init__(self, outputs, job_id='job-1'):
        self.outputs, self.id = outputs, job_id


class PreserveContractTests(unittest.TestCase):
    def test_frame_sampling_is_even_and_includes_the_first_frame(self):
        self.assertEqual(frame_indices(1), [0])
        self.assertEqual(frame_indices(3, 4), [0, 1, 2])
        self.assertEqual(frame_indices(13, 4), [0, 4, 8, 12])
        self.assertEqual(frame_indices(56, 4), [0, 18, 37, 55])
        for total in (0, -1, True, 1.5):
            with self.subTest(total=total), self.assertRaises(ValueError):
                frame_indices(total)

    def test_description_must_be_one_short_sentence_about_the_clip(self):
        self.assertEqual(validate_preserved('  two   spaces '), 'two spaces')
        self.assertEqual(validate_preserved('Snow, a staff and a hooded cloak.'),
                         'Snow, a staff and a hooded cloak.')
        for bad in ('', '   ', None, 5, 'x' * 401,
                    'The target video shows [Shot 1] the woman walking.',
                    'At 00:03.000 the shot cuts to a close-up.',
                    'shot 1: the woman catches the bottle'):
            with self.subTest(bad=str(bad)[:40]), self.assertRaises(ValueError):
                validate_preserved(bad)

    def test_graph_wires_every_frame_into_one_vision_call(self):
        graph = build_preserve_graph(['a.png', 'b.png', 'c.png'])
        self.assertEqual([graph[str(30 + i)]['inputs']['image'] for i in range(3)],
                         ['a.png', 'b.png', 'c.png'])
        self.assertEqual(graph['10']['inputs']['inputcount'], 3)
        self.assertEqual(graph['10']['inputs']['image_3'], ['32', 0])
        self.assertEqual(graph['40']['class_type'], VISION_NODE)
        self.assertEqual(graph['40']['inputs']['image'], ['10', 0])
        self.assertEqual(graph['40']['inputs']['custom_prompt'], INSTRUCTION)
        self.assertIn('must remain unchanged', graph['40']['inputs']['custom_prompt'])
        self.assertEqual(graph['40']['inputs']['model_name'], VISION_MODEL)
        self.assertEqual(graph['50']['class_type'], SAVE_NODE)
        self.assertEqual(graph['50']['inputs']['text'], ['40', 0])
        self.assertEqual(graph['50']['inputs']['format'], 'txt')
        self.assertNotIn('video', [node['class_type'] for node in graph.values()])
        with self.assertRaises(ValueError):
            build_preserve_graph([])
        with self.assertRaises(ValueError):
            build_preserve_graph(['a.png'], instruction='   ')

    def test_saved_text_is_read_from_a_file_output(self):
        job = FakeJob([FakeOutput('preserve_00001.txt', 'text/plain', b'a staff and snow')])
        self.assertEqual(_saved_text(job), 'a staff and snow')
        with self.assertRaises(RuntimeError):
            _saved_text(FakeJob([FakeOutput('x.json', 'application/json', b'{}')]))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_sampling_writes_distinct_frames_from_a_real_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip = root / 'clip.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi',
                            '-i', 'testsrc2=size=64x64:rate=24:duration=1',
                            '-c:v', 'libx264', str(clip)], check=True)
            frames = sample_frames(clip, root / 'frames', FRAME_COUNT)
            self.assertEqual(len(frames), FRAME_COUNT)
            payloads = [frame.read_bytes() for frame in frames]
            self.assertEqual(len(set(payloads)), FRAME_COUNT)


if __name__ == '__main__':
    unittest.main()
