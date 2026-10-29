"""Permanent Take deletion: guards, cascade and reclaimed bytes.

The store is immutable on purpose, so these tests build real read-only trees and
prove that deletion restores permission only for what it removes.
"""
from pathlib import Path
import json
import os
import stat
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from continuable_take_api import create_router
from continuable_take_delete import TakeDeletionRefused, delete_take

KEEP = 'a' * 32
CHILD = 'b' * 32
GRANDCHILD = 'c' * 32
OTHER = 'd' * 32


def capsule(parent=None):
    body = {'format': 'opengenjutsu-continuable-take', 'schema_version': 1,
            'lineage': {'relation': 'extends'}, 'origin': {'source_job': 'job'}}
    if parent:
        body['lineage']['parent_id'] = parent
    return body


class TakeFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.store = self.work / 'timeline' / 'continuable-takes'
        self.store.mkdir(parents=True)

    def tearDown(self):
        for root, directories, files in os.walk(self.tmp.name):
            for name in directories + files:
                try:
                    os.chmod(os.path.join(root, name), stat.S_IRWXU)
                except OSError:
                    pass
        self.tmp.cleanup()

    def make(self, take_id, parent=None, payload=b'x' * 64, media=True):
        directory = self.store / take_id
        directory.mkdir()
        (directory / 'capsule.json').write_text(json.dumps(capsule(parent)))
        video = directory / 'take.mp4'
        video.write_bytes(payload)
        # Immutable by design: the app cannot rewrite evidence later.
        os.chmod(video, 0o400)
        os.chmod(directory, 0o500)
        if media:
            copy = self.work / 'media' / ('forward-' + take_id)
            copy.mkdir(parents=True)
            (copy / 'take.mp4').write_bytes(payload)
            os.chmod(copy / 'take.mp4', 0o400)
        return directory

    def attempt(self, take_id, status):
        target = self.work / 'native-attempts' / 'native-attempts' / ('e' * 32)
        target.mkdir(parents=True, exist_ok=True)
        (target / 'attempt.json').write_text(json.dumps({'take_id': take_id, 'status': status}))


class DeleteRules(TakeFixture):
    def test_leaf_take_and_its_forward_copy_are_removed_and_bytes_reported(self):
        self.make(OTHER)
        result = delete_take(self.work, OTHER)
        self.assertEqual(result['deleted'], [OTHER])
        self.assertGreaterEqual(result['bytes'], 128)
        self.assertFalse((self.store / OTHER).exists())
        self.assertFalse((self.work / 'media' / ('forward-' + OTHER)).exists())

    def test_unknown_or_malformed_identifier_is_refused(self):
        for value in ('f' * 32, '../' + OTHER, 'A' * 32):
            with self.subTest(value=value):
                with self.assertRaises(TakeDeletionRefused):
                    delete_take(self.work, value)

    def test_take_with_children_is_refused_until_a_cascade_is_asked_for(self):
        self.make(KEEP)
        self.make(CHILD, parent=KEEP)
        self.make(GRANDCHILD, parent=CHILD)
        with self.assertRaises(TakeDeletionRefused) as caught:
            delete_take(self.work, KEEP)
        self.assertIn('2 later Takes', str(caught.exception))
        self.assertTrue((self.store / GRANDCHILD).exists())
        result = delete_take(self.work, KEEP, cascade=True)
        self.assertEqual(sorted(result['deleted']), sorted([KEEP, CHILD, GRANDCHILD]))
        for take_id in (KEEP, CHILD, GRANDCHILD):
            self.assertFalse((self.store / take_id).exists())

    def test_generation_in_flight_blocks_deletion(self):
        self.make(OTHER)
        for status in ('running', 'queued', 'pending'):
            with self.subTest(status=status):
                self.attempt(OTHER, status)
                with self.assertRaises(TakeDeletionRefused) as caught:
                    delete_take(self.work, OTHER)
                self.assertIn('still being generated', str(caught.exception))
                self.assertTrue((self.store / OTHER).exists())
                (self.work / 'native-attempts' / 'native-attempts' / ('e' * 32) / 'attempt.json').unlink()

    def test_finished_attempt_does_not_block_deletion(self):
        self.make(OTHER)
        self.attempt(OTHER, 'done')
        self.assertEqual(delete_take(self.work, OTHER)['deleted'], [OTHER])

    def test_symlinked_take_directory_is_never_followed(self):
        outside = self.work / 'outside'
        outside.mkdir()
        (outside / 'precious.txt').write_text('keep me')
        (self.store / OTHER).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(TakeDeletionRefused):
            delete_take(self.work, OTHER)
        self.assertTrue((outside / 'precious.txt').exists())


class DeleteRoute(TakeFixture):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(create_router(lambda: self.work))
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_route_deletes_and_returns_reclaimed_bytes(self):
        self.make(OTHER)
        response = self.client.delete('/api/continuity/takes/' + OTHER)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['deleted'], [OTHER])
        self.assertGreater(body['bytes'], 0)
        self.assertEqual(self.client.delete('/api/continuity/takes/' + OTHER).status_code, 404)

    def test_route_refuses_children_without_cascade_then_accepts_it(self):
        self.make(KEEP)
        self.make(CHILD, parent=KEEP)
        refused = self.client.delete('/api/continuity/takes/' + KEEP)
        self.assertEqual(refused.status_code, 409)
        self.assertIn('later Take', refused.json()['detail'])
        accepted = self.client.delete('/api/continuity/takes/' + KEEP, params={'cascade': 'true'})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(sorted(accepted.json()['deleted']), sorted([KEEP, CHILD]))

    def test_route_reports_live_generation_as_a_conflict(self):
        self.make(OTHER)
        self.attempt(OTHER, 'running')
        response = self.client.delete('/api/continuity/takes/' + OTHER)
        self.assertEqual(response.status_code, 409)
        self.assertIn('still being generated', response.json()['detail'])

    def test_route_rejects_malformed_identifier(self):
        self.assertEqual(self.client.delete('/api/continuity/takes/not-a-take').status_code, 422)


if __name__ == '__main__':
    unittest.main()
