"""A direction becomes an H3 prompt before any video work starts."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_forward_api as api  # noqa: E402


class FakeRequest:
    def __init__(self, **values):
        self.__dict__.update(values)

    def model_copy(self, update):
        return FakeRequest(**dict(self.__dict__, **update))


def fake_client(status):
    class Job:
        id = 'prompt-job'

    Job.status = status

    class Client:
        class workflows:
            @staticmethod
            def from_json(graph):
                return graph

        def run(self, workflow, timeout=None):
            return Job()

    client = Client()
    client.assets = type('A', (), {'from_file': staticmethod(
        lambda p: type('R', (), {'as_reference': lambda s: {
            '__type': 'core/ASSET', 'info': {'id': 'committed-ref'}}})())})()
    return client


class RefineTests(unittest.TestCase):
    def runner(self, client):
        return api.make_forward_runner(client_factory=lambda: client,
                                       models_factory=lambda: 'models',
                                       fingerprint='f' * 64, work_root='/ops')

    def test_the_runner_sends_the_refined_prompt_not_the_direction(self):
        request = FakeRequest(request_id='a' * 32, prompt='she keeps walking',
                              seed=7, raw_frames=158)
        with patch.object(api, 'parent_references', return_value=[Path('/ref.png')]), \
             patch.object(api, 'refine_prompt', return_value='REFINED PROMPT') as refine, \
             patch.object(api, 'submit_forward', return_value={'take_id': 'f' * 32}) as submit:
            self.runner(fake_client('succeeded')).__call__('/work', 'b' * 32, request)
        refine.assert_called_once()
        self.assertEqual(submit.call_args.args[2].prompt, 'REFINED PROMPT')
        self.assertEqual(request.prompt, 'she keeps walking', 'the request is not mutated')

    def test_a_failed_refiner_stops_before_any_video_work(self):
        with patch.object(api, 'parent_references', return_value=[Path('/ref.png')]), \
             patch.object(api, 'submit_forward') as submit:
            with self.assertRaisesRegex(ValueError, 'could not be prepared'):
                self.runner(fake_client('failed')).__call__(
                    '/work', 'b' * 32,
                    FakeRequest(request_id='a' * 32, prompt='x', seed=1, raw_frames=158))
        submit.assert_not_called()

    def test_two_references_are_refused_before_any_job(self):
        with patch.object(api, 'parent_references',
                          return_value=[Path('/a.png'), Path('/b.png')]), \
             patch.object(api, 'submit_forward') as submit:
            with self.assertRaisesRegex(ValueError, 'two character references|2 character'):
                self.runner(fake_client('succeeded')).__call__(
                    '/work', 'b' * 32,
                    FakeRequest(request_id='a' * 32, prompt='x', seed=1, raw_frames=158))
        submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
