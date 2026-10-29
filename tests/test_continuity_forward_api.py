"""The Forward route refuses for free and never invents a take."""
import sys
from pathlib import Path
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from continuity_forward_api import create_forward_router  # noqa: E402

BODY = {'request_id': 'a' * 32, 'prompt': 'she keeps walking', 'seed': 7, 'raw_frames': 56}


def app_with(runner):
    app = FastAPI()
    app.include_router(create_forward_router(lambda: Path('/work'), runner=runner))
    return TestClient(app)


class ForwardRouteTests(unittest.TestCase):
    def test_a_successful_request_returns_the_operation_view(self):
        seen = {}

        def runner(work, take_id, request):
            seen.update(work=work, take_id=take_id, prompt=request.prompt)
            return {'take_id': 'f' * 32, 'status': 'waiting'}

        response = app_with(runner).post('/api/continuity/takes/' + 'b' * 32 + '/forward',
                                         json=BODY)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['take_id'], 'f' * 32)
        self.assertEqual(seen['take_id'], 'b' * 32)
        self.assertEqual(seen['work'], '/work')

    def test_a_refusal_is_reported_without_a_take(self):
        def runner(work, take_id, request):
            raise ValueError('This take is too short to continue from its end.')

        response = app_with(runner).post('/api/continuity/takes/' + 'b' * 32 + '/forward',
                                         json=BODY)
        self.assertEqual(response.status_code, 422)
        self.assertIn('could not be continued', response.json()['detail'])

    def test_private_runner_errors_are_never_echoed_to_the_browser(self):
        marker = 'PRIVATE_' + 'PROMPT_TOKEN /private/source.wav'
        def runner(*args):
            raise ValueError(marker)
        response = app_with(runner).post('/api/continuity/takes/' + 'b' * 32 + '/forward', json=BODY)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(marker, response.text)
        self.assertNotIn('/private/', response.text)

    def test_an_unknown_take_is_a_404(self):
        def runner(work, take_id, request):
            raise FileNotFoundError(take_id)

        response = app_with(runner).post('/api/continuity/takes/' + 'b' * 32 + '/forward',
                                         json=BODY)
        self.assertEqual(response.status_code, 404)

    def test_the_route_refuses_a_request_that_names_a_graph_or_a_path(self):
        client = app_with(lambda *a: {'take_id': 'f' * 32})
        for field in ('graph', 'path', 'target', 'backend', 'parent_take_id'):
            with self.subTest(field=field):
                body = dict(BODY, **{field: 'x'})
                response = client.post('/api/continuity/takes/' + 'b' * 32 + '/forward',
                                       json=body)
                self.assertEqual(response.status_code, 422, field)

    def test_an_unconfigured_instance_says_so(self):
        response = app_with(None).post('/api/continuity/takes/' + 'b' * 32 + '/forward',
                                       json=BODY)
        self.assertEqual(response.status_code, 503)


if __name__ == '__main__':
    unittest.main()
