"""Native rail persistence in existing projects; isolated HTTP/TDD contracts."""
from copy import deepcopy
import json
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import continuable_take
from test_timeline_store import IsolatedTimeline
from timeline_api import create_router
from timeline_store import TimelineStore, atomic_json


class NativeWorkspaceApiTests(IsolatedTimeline):
    def setUp(self):
        super().setUp()
        self.client = self.enterContext(TestClient(self.app()))
        response = self.client.post('/api/timeline/projects', json={'title': 'Sequence'})
        self.assertEqual(response.status_code, 201, response.text)
        self.project = response.json()
        self.base = '/api/timeline/projects/' + self.project['project_id']
        self.url = self.base + '/native-workspace'
        self.path = self.store._path('projects', self.project['project_id'])
        self.take_id, self.other_take = 'a' * 32, 'b' * 32
        self.first, self.second = '1' * 32, '2' * 32
        self.reader = self.enterContext(patch.object(continuable_take, 'get_take',
                                                   side_effect=self.metadata))

    def app(self):
        app = FastAPI()
        app.include_router(create_router(lambda: self.work, lambda: self.media, 2_000_000))
        return app

    def metadata(self, work, take_id):
        self.assertEqual(work, self.work)
        if take_id not in {self.take_id, self.other_take}:
            raise FileNotFoundError('/private/unknown')
        return object()  # Metadata existence only; no media/family inspection.

    def payload(self, **overrides):
        data = {'revision': 0,
                'placements': [{'placement_id': self.first, 'take_id': self.take_id}],
                'selected_placement_id': self.first,
                'drafts': {self.first: {'prompt': '', 'seed': '', 'raw_frames': 277}}}
        data.update(overrides)
        return data

    def save(self, payload=None):
        response = self.client.patch(self.url, json=payload or self.payload())
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def rejected(self, payload, status=422, url=None):
        before = self.path.read_bytes()
        response = self.client.patch(url or self.url, json=payload)
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertNotIn(str(self.work), response.text)
        return response

    def test_existing_project_empty_view_is_read_only(self):
        before, stamp = self.path.read_bytes(), self.path.stat().st_mtime_ns
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            'project_id': self.project['project_id'], 'title': 'Sequence', 'revision': 0,
            'placements': [], 'selected_placement_id': None, 'drafts': {},
            'updated_at': self.project['updated_at']})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, stamp)
        self.assertNotIn('native_workspace', json.loads(before))
        self.reader.assert_not_called()

    def test_save_reopen_same_project_and_precise_seed(self):
        payload = self.payload(title='  Native sequence  ')
        payload['drafts'][self.first] = {'prompt': 'Continue quietly',
                                       'seed': '18446744073709551615', 'raw_frames': 277}
        saved = self.save(payload)
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['title'], 'Native sequence')
        for key in ('placements', 'selected_placement_id', 'drafts'):
            self.assertEqual(saved[key], payload[key])
        self.assertEqual(set(saved), {'project_id', 'title', 'revision', 'placements',
                                     'selected_placement_id', 'drafts', 'updated_at'})
        self.assertGreaterEqual(saved['updated_at'], self.project['updated_at'])
        self.assertEqual(self.client.get(self.url).json(), saved)
        fresh = TimelineStore(self.work, self.media, 2_000_000)
        self.assertEqual(fresh.get_native_workspace(self.project['project_id']), saved)
        with TestClient(self.app()) as client:
            self.assertEqual(client.get(self.url).json(), saved)
        self.assertEqual(len(list((self.work / 'timeline' / 'projects').glob('*.json'))), 1)
        self.assertEqual(list((self.work / 'timeline' / 'takes').iterdir()), [])

    def test_order_is_explicit_and_same_take_can_have_two_placements(self):
        placements = [{'placement_id': self.second, 'take_id': self.take_id},
                      {'placement_id': self.first, 'take_id': self.take_id}]
        saved = self.save(self.payload(placements=placements, selected_placement_id=None,
                                      drafts={self.second: {'prompt': 'Other', 'seed': '0'}}))
        self.assertEqual(saved['placements'], placements)
        self.assertIsNone(saved['selected_placement_id'])
        self.assertEqual(saved['drafts'][self.second]['raw_frames'], 277)

    def test_conflict_does_not_write_or_validate_takes(self):
        self.save()
        self.reader.reset_mock()
        self.rejected(self.payload(title='Lost edit'), 409)
        self.reader.assert_not_called()

    def test_legacy_edits_and_native_edits_preserve_each_other(self):
        # A legacy take manifest is enough: these edits must not inspect media.
        clip_id, legacy_take = '3' * 32, '4' * 32
        manifest = json.loads(self.path.read_text())
        manifest['known_clips'][clip_id] = {
            'clip_id': clip_id, 'take_id': legacy_take, 'label': 'Legacy',
            'engine': 'upload', 'source_job_id': None}
        manifest['clips'] = [{'clip_id': clip_id, 'in_frame': 0, 'out_frame': 12}]
        atomic_json(self.store._path('takes', legacy_take, 'take.json'),
                    {'width': 64, 'height': 48, 'fps': 12, 'frames': 12})
        atomic_json(self.path, manifest)
        self.save()
        persisted = json.loads(self.path.read_text())
        self.assertEqual(persisted['clips'], manifest['clips'])
        self.assertEqual(persisted['known_clips'], manifest['known_clips'])
        native = deepcopy(persisted['native_workspace'])
        response = self.client.patch(self.base, json={
            'revision': 1, 'title': 'Legacy edit',
            'clips': [{'clip_id': clip_id, 'in_frame': 2, 'out_frame': 8}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('native_workspace', response.json())
        self.assertNotIn('placements', response.json())
        persisted = json.loads(self.path.read_text())
        self.assertEqual(persisted['native_workspace'], native)
        self.assertEqual(self.client.get(self.url).json()['revision'], 2)
        self.rejected(self.payload(revision=1), 409)
        self.save(self.payload(revision=2, title='Native edit'))
        persisted_after = json.loads(self.path.read_text())
        self.assertEqual(persisted_after['clips'], persisted['clips'])
        self.assertEqual(persisted_after['known_clips'], persisted['known_clips'])
        self.assertEqual(self.client.get(self.base).json()['title'], 'Native edit')

    def test_missing_and_malformed_project_ids(self):
        for bad in ('bad', 'A' * 32, 'a' * 31, 'x%2Fy'):
            with self.subTest(project_id=bad):
                url = '/api/timeline/projects/' + bad + '/native-workspace'
                expected = 404 if '%2F' in bad else 422
                self.assertEqual(self.client.get(url).status_code, expected)
                self.rejected(self.payload(), expected, url)
        missing = '/api/timeline/projects/' + 'f' * 32 + '/native-workspace'
        self.assertEqual(self.client.get(missing).status_code, 404)
        self.rejected(self.payload(), 404, missing)

    def test_unknown_take_and_storage_errors_are_sanitized_and_atomic(self):
        data = self.payload(placements=[{'placement_id': self.first, 'take_id': 'f' * 32}])
        response = self.rejected(data, 404)
        self.assertIn('Take', response.json()['detail'])
        for error, status in ((ValueError('/private/capsule'), 422),
                              (PermissionError('/private/secret'), 503)):
            with self.subTest(error=error):
                self.reader.side_effect = error
                response = self.rejected(self.payload(), status)
                self.assertNotIn('/private', response.text)

    def test_rejects_invalid_top_level_and_placement_values(self):
        invalid = [self.payload(**extra) for extra in (
            {'revision': True}, {'revision': '0'}, {'revision': -1},
            {'revision': 2**53}, {'title': None}, {'title': ''}, {'title': ' '},
            {'title': 'x' * 161}, {'title': 1}, {'path': '/private'},
            {'selected_placement_id': self.second}, {'selected_placement_id': 'bad'})]
        for field in ('revision', 'placements', 'selected_placement_id', 'drafts'):
            data = self.payload()
            del data[field]
            invalid.append(data)
        for field in ('placement_id', 'take_id'):
            for bad in ('../secret', 'A' * 32, 'a' * 31, 'a' * 32 + '\n', 123, None):
                data = self.payload()
                data['placements'][0][field] = bad
                invalid.append(data)
        data = self.payload()
        data['placements'][0]['path'] = '/private'
        invalid.extend([data, self.payload(placements=self.payload()['placements'] * 2),
                        self.payload(placements=None), self.payload(drafts=None)])
        for data in invalid:
            with self.subTest(data=data):
                self.rejected(data)
        self.reader.assert_not_called()

    def test_drafts_are_strict_bounded_and_only_for_present_placements(self):
        drafts = [{self.second: {'prompt': '', 'seed': '', 'raw_frames': 277}},
                  {'../secret': {'prompt': '', 'seed': '', 'raw_frames': 277}}]
        for field, values in (
                ('prompt', [None, 42, 'x' * 4001]),
                ('seed', [None, 0, True, '-1', '+1', '1.0', '1e3', ' 1', '1 ',
                          '1\n', '١', '18446744073709551616', '9' * 5000]),
                ('raw_frames', [None, True, '277', 277.0, 4, 6, 276, 3601])):
            for value in values:
                draft = {'prompt': '', 'seed': '', 'raw_frames': 277, field: value}
                drafts.append({self.first: draft})
        drafts.append({self.first: {'prompt': '', 'seed': '', 'raw_frames': 277,
                                    'take_path': '/secret'}})
        for field in ('prompt', 'seed'):
            draft = {'prompt': '', 'seed': '', 'raw_frames': 277}
            del draft[field]
            drafts.append({self.first: draft})
        for draft in drafts:
            with self.subTest(draft=draft):
                self.rejected(self.payload(drafts=draft))
        self.reader.assert_not_called()

    def test_max_placements_and_raw_frame_grid_boundaries(self):
        placements = [{'placement_id': f'{i:032x}', 'take_id': self.take_id}
                      for i in range(256)]
        self.rejected(self.payload(placements=placements + [
            {'placement_id': 'f' * 32, 'take_id': self.take_id}],
            selected_placement_id=None, drafts={}))
        saved = self.save(self.payload(placements=placements, selected_placement_id=None, drafts={}))
        self.assertEqual(len(saved['placements']), 256)
        for revision, frames in enumerate((5, 3592), start=1):
            data = self.payload(revision=revision)
            data['drafts'][self.first]['raw_frames'] = frames
            self.assertEqual(self.save(data)['drafts'][self.first]['raw_frames'], frames)

    def test_real_capsule_with_corrupt_media_is_still_placeable(self):
        import test_continuable_take as fixtures
        fixture = fixtures.ContinuableTakeTests('test_success_frozen_record_and_fixed_private_copies')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.work = self.work
        fixture.do_import()
        fixture.rewrite('take.cond.safetensors', b'corrupt')
        # Exercise the actual bounded capsule reader, not the metadata double.
        self.reader.side_effect = self.real_get_take
        before = {p.name: p.read_bytes() for p in fixture.directory.iterdir()}
        with patch.object(continuable_take, 'get_validated_family',
                          side_effect=AssertionError('Must not inspect media')):
            self.save()
        self.assertEqual({p.name: p.read_bytes() for p in fixture.directory.iterdir()}, before)

    real_get_take = staticmethod(continuable_take.get_take)

    def test_clear_rail_removes_selection_and_drafts(self):
        self.save()
        saved = self.save(self.payload(revision=1, placements=[],
                                       selected_placement_id=None, drafts={}))
        self.assertEqual(saved['placements'], [])
        self.assertEqual(saved['drafts'], {})
        self.assertIsNone(saved['selected_placement_id'])
        self.assertEqual(self.client.get(self.url).json(), saved)

    def test_concurrent_routers_share_project_revision_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        with TestClient(self.app()) as second_client:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(client.patch, self.url, json=self.payload(title=title))
                           for client, title in ((self.client, 'First'), (second_client, 'Second'))]
                responses = [future.result() for future in futures]
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        saved = next(response.json() for response in responses if response.status_code == 200)
        self.assertEqual(self.client.get(self.url).json(), saved)
        self.assertEqual(saved['revision'], 1)

    def test_unknown_later_take_does_not_partially_save(self):
        data = self.payload(placements=[
            {'placement_id': self.first, 'take_id': self.take_id},
            {'placement_id': self.second, 'take_id': 'f' * 32}], title='Not saved')
        self.rejected(data, 404)
        self.assertEqual(self.client.get(self.base).json(), self.project)

    def test_empty_prompt_and_decimal_seed_are_preserved_exactly(self):
        data = self.payload()
        data['drafts'][self.first] = {'prompt': '', 'seed': '00001234'}
        saved = self.save(data)
        self.assertEqual(saved['drafts'][self.first],
                         {'prompt': '', 'seed': '00001234', 'raw_frames': 277})

    def test_project_symlink_is_never_followed(self):
        target = self.work / 'outside.json'
        before = self.path.read_bytes()
        target.write_bytes(before)
        self.path.unlink()
        self.path.symlink_to(target)
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assertEqual(self.client.patch(self.url, json=self.payload()).status_code, 409)
        self.assertEqual(target.read_bytes(), before)
