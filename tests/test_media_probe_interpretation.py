"""How a probe payload becomes a frame rate and a duration.

FFmpeg reports ``avg_frame_rate`` as *frames / duration*. When a container ends
one frame short, that quotient is not the rate the file was written at: 72
frames over 2.958333 s reads as 24.338 fps instead of 24. The declared
``r_frame_rate`` stays exact, so the interpretation prefers it whenever the two
agree to within two percent, and falls back to the average for genuinely
variable footage.
"""
import unittest

from media_probe import _interpret


def payload(**stream):
    return {'streams': [{'width': 1280, 'height': 720, **stream}],
            'format': {'duration': stream.get('duration')}}


class InterpretationTests(unittest.TestCase):
    def test_exact_container_keeps_its_rate(self):
        media = _interpret(payload(nb_read_frames='72', avg_frame_rate='24/1',
                                   r_frame_rate='24/1', duration='3.000000'))
        self.assertEqual((media['frames'], media['fps'], media['duration']),
                         (72, 24.0, 3.0))

    def test_one_frame_short_container_keeps_the_declared_rate(self):
        media = _interpret(payload(nb_read_frames='72', avg_frame_rate='3456/142',
                                   r_frame_rate='24/1', duration='2.958333'))
        self.assertEqual((media['frames'], media['fps'], media['duration']),
                         (72, 24.0, 3.0))

    def test_variable_footage_keeps_the_average(self):
        media = _interpret(payload(nb_read_frames='240', avg_frame_rate='24/1',
                                   r_frame_rate='30/1', duration='10.000000'))
        self.assertEqual(media['fps'], 24.0)
        self.assertEqual(media['duration'], 10.0)

    def test_missing_duration_is_derived_from_frames(self):
        media = _interpret({'streams': [{'width': 640, 'height': 360,
                                         'nb_read_frames': '48',
                                         'avg_frame_rate': '24/1',
                                         'r_frame_rate': '24/1'}]})
        self.assertEqual((media['frames'], media['fps'], media['duration']),
                         (48, 24.0, 2.0))

    def test_a_stream_without_video_is_refused(self):
        with self.assertRaises(ValueError):
            _interpret({'streams': []})


if __name__ == '__main__':
    unittest.main()
