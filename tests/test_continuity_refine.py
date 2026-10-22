"""A forward runs the pump: describe the references, format them, then generate.

The fixed English template is gone. What reaches the graph is the text produced by
the R2VA generator, fed with descriptions read from the actual reference images.
"""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_forward_api as api  # noqa: E402

DIRECTION = 'She keeps walking, then slows down and looks over her shoulder.'
REFINED = 'subject_definitions:\n<Subject 1> is the character in <Picture 1>...'


class FakeRequest:
    def __init__(self, **values):
        self.__dict__.update(values)

    def model_copy(self, update):
        return FakeRequest(**dict(self.__dict__, **update))


def fake_client():
    class Client:
        class workflows:
            @staticmethod
            def from_json(graph):
                return graph

        def run(self, workflow, timeout=None):
            raise AssertionError('no job may run outside the pump')

    client = Client()
    client.assets = type('A', (), {'from_file': staticmethod(
        lambda p: type('R', (), {'as_reference': lambda s: {
            '__type': 'core/ASSET', 'info': {'id': 'committed-ref'}}})())})()
    return client


class PumpTests(unittest.TestCase):
    def runner(self, client):
        return api.make_forward_runner(client_factory=lambda: client,
                                       models_factory=lambda: 'models',
                                       fingerprint='f' * 64, work_root='/ops')

    def test_the_refined_text_is_what_reaches_the_graph(self):
        request = FakeRequest(request_id='a' * 32, prompt=DIRECTION, seed=7, raw_frames=158)
        with patch.object(api, 'parent_references', return_value=[Path('/ref.png')]), \
             patch.object(api, 'describe_reference', return_value='blue ponytail, dark suit'), \
             patch.object(api, 'refine_prompt', return_value=REFINED) as refine, \
             patch.object(api, 'submit_forward', return_value={'take_id': 'f' * 32}) as submit:
            self.runner(fake_client())('/work', 'b' * 32, request)
        self.assertEqual(submit.call_args.args[2].prompt, REFINED)
        direction = refine.call_args.args[1]
        self.assertIn('<Subject 1> is the character shown in <Picture 1>', direction)
        self.assertIn('blue ponytail, dark suit', direction)
        self.assertIn(DIRECTION, direction)

    def test_a_failed_description_stops_before_any_video_work(self):
        with patch.object(api, 'parent_references', return_value=[Path('/ref.png')]), \
             patch.object(api, 'describe_reference', side_effect=ValueError('no description')), \
             patch.object(api, 'submit_forward') as submit:
            with self.assertRaises(ValueError):
                self.runner(fake_client())(
                    '/work', 'b' * 32,
                    FakeRequest(request_id='a' * 32, prompt=DIRECTION, seed=7, raw_frames=158))
        submit.assert_not_called()

    def test_a_failed_formatter_stops_before_any_video_work(self):
        with patch.object(api, 'parent_references', return_value=[Path('/ref.png')]), \
             patch.object(api, 'describe_reference', return_value='a character'), \
             patch.object(api, 'refine_prompt', side_effect=ValueError('could not be prepared')), \
             patch.object(api, 'submit_forward') as submit:
            with self.assertRaises(ValueError):
                self.runner(fake_client())(
                    '/work', 'b' * 32,
                    FakeRequest(request_id='a' * 32, prompt=DIRECTION, seed=7, raw_frames=158))
        submit.assert_not_called()

    def test_several_references_are_described_and_passed_in_order(self):
        with patch.object(api, 'parent_references',
                          return_value=[Path('/a.png'), Path('/b.png')]), \
             patch.object(api, 'describe_reference', side_effect=['first', 'second']), \
             patch.object(api, 'refine_prompt', return_value=REFINED) as refine, \
             patch.object(api, 'submit_forward', return_value={'take_id': 'f' * 32}) as submit:
            self.runner(fake_client())(
                '/work', 'b' * 32,
                FakeRequest(request_id='a' * 32, prompt=DIRECTION, seed=7, raw_frames=158))
        direction = refine.call_args.args[1]
        self.assertLess(direction.index('first'), direction.index('second'))
        self.assertEqual(len(submit.call_args.kwargs['references']), 2)

if __name__ == '__main__':
    unittest.main()
