"""Synthetic HTTP state doubles; this suite submits no jobs."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import continuable_take_api as api
from h3_av_state import child_state, tail_fits
from test_h3_av_state import PARENT_OK, PARENT_DEAD


class DurationReadinessTests(unittest.TestCase):
    def read(self, state, *, error=None):
        app = FastAPI()
        app.include_router(api.create_router(lambda: Path('/unused')))
        family = SimpleNamespace(record=SimpleNamespace(to_manifest=lambda: {
            'family': {'context': {'delivered_frames': 123, 'fps': 24}}}))
        with patch.object(api, 'get_take'), patch.object(api, 'get_validated_family', return_value=family), \
             patch('h3_av_state.state_from_family', return_value=state, side_effect=error):
            result = TestClient(app).get('/api/continuity/takes/' + 'a'*32 + '/readiness')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['cache-control'], 'private, no-store')
        return result.json()

    def test_choices_are_parent_specific_seconds_and_accepted_children(self):
        a = self.read(PARENT_OK)
        b = self.read(child_state(PARENT_OK, 158))
        self.assertTrue(a['extend'])
        self.assertTrue(b['extend'])
        self.assertIn(158, [x['raw_frames'] for x in a['duration_options']])
        self.assertNotIn(158, [x['raw_frames'] for x in b['duration_options']])
        for parent, result in ((PARENT_OK, a), (child_state(PARENT_OK, 158), b)):
            for option in result['duration_options']:
                child = child_state(parent, option['raw_frames'])
                self.assertTrue(tail_fits(child))
                self.assertGreaterEqual(child.delivered_frames, 39)
                self.assertAlmostEqual(option['seconds'], child.delivered_frames / 24)

    def test_unusable_parent_has_no_duration_choices(self):
        data = self.read(PARENT_DEAD)
        self.assertTrue(data['verified'])
        self.assertFalse(data['extend'])
        self.assertEqual(data['duration_options'], [])

    def test_unreadable_timing_fails_closed_instead_of_assuming_ready(self):
        for error in (None, ValueError('/private/secret')):
            data = self.read(None, error=error)
            self.assertTrue(data['verified'])
            self.assertFalse(data['extend'])
            self.assertEqual(data['duration_options'], [])
            self.assertNotIn('/private', str(data))
            self.assertTrue(data['reason'])
