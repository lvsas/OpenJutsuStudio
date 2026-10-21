"""A continuation carries the operator's own words, and nothing else.

The R2VA refiner writes a complete new-video description. Sent as a continuation
prompt it produced a measurable hard cut three frames in, so the forward path must
never use it. Refinement belongs to root takes, where a whole video is described.
"""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_forward_api as api  # noqa: E402

DIRECTION = 'She keeps walking, then slows down and looks over her shoulder.'


class FakeRequest:
    def __init__(self, **values):
        self.__dict__.update(values)


def fake_client():
    class Client:
        class workflows:
            @staticmethod
            def from_json(graph):
                return graph

        def run(self, workflow, timeout=None):
            raise AssertionError('no prompt job may run for a continuation')

    client = Client()
    client.assets = type('A', (), {'from_file': staticmethod(
        lambda p: type('R', (), {'as_reference': lambda s: {
            '__type': 'core/ASSET', 'info': {'id': 'committed-ref'}}})())})()
    return client


class ContinuationPromptTests(unittest.TestCase):
    def runner(self, client):
        return api.make_forward_runner(client_factory=lambda: client,
                                       models_factory=lambda: 'models',
                                       fingerprint='f' * 64, work_root='/ops')

    def test_the_operator_direction_reaches_the_graph_unchanged(self):
        request = FakeRequest(request_id='a' * 32, prompt=DIRECTION, seed=7, raw_frames=158)
        with patch.object(api, 'parent_references', return_value=[Path('/ref.png')]), \
             patch.object(api, 'submit_forward', return_value={'take_id': 'f' * 32}) as submit:
            self.runner(fake_client())('/work', 'b' * 32, request)
        self.assertEqual(submit.call_args.args[2].prompt, DIRECTION)

    def test_no_refinement_job_is_submitted(self):
        """The client raises if anything runs a job before the forward itself."""
        with patch.object(api, 'parent_references', return_value=[Path('/ref.png')]), \
             patch.object(api, 'submit_forward', return_value={'take_id': 'f' * 32}):
            self.runner(fake_client())(
                '/work', 'b' * 32,
                FakeRequest(request_id='a' * 32, prompt=DIRECTION, seed=7, raw_frames=158))

    def test_two_references_are_refused_before_any_job(self):
        with patch.object(api, 'parent_references',
                          return_value=[Path('/a.png'), Path('/b.png')]), \
             patch.object(api, 'submit_forward') as submit:
            with self.assertRaisesRegex(ValueError, 'character references'):
                self.runner(fake_client())(
                    '/work', 'b' * 32,
                    FakeRequest(request_id='a' * 32, prompt=DIRECTION, seed=7, raw_frames=158))
        submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
