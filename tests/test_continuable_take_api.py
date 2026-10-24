"""Read-only HTTP contract; synthetic envelope fixtures, NOT native render proof."""
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import test_continuable_take as fixtures
import continuable_take_api as api


class ContinuableTakeApiTests(unittest.TestCase):
    def setUp(self):
        # Reuse the explicitly synthetic family without inheriting/rerunning its tests.
        self.fixture = fixtures.ContinuableTakeTests(
            'test_success_frozen_record_and_fixed_private_copies')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # HTTP-only cases use synthetic MP4 bytes. The real preview guard below
        # explicitly stops this double and exercises FFmpeg/remux/cache itself.
        self.preview_double = patch.object(api, 'prepare_preview',
            side_effect=lambda work, family: family.video)
        self.preview_double.start()
        self.addCleanup(self.preview_double.stop)
        self.app = FastAPI()
        self.app.include_router(api.create_router(lambda: self.fixture.work))
        self.client = self.enterContext(TestClient(self.app))
        self.url = '/api/continuity/takes/' + self.fixture.take_id

    def imported(self):
        return self.fixture.do_import()

    def test_empty_registry_does_not_create_work(self):
        self.assertFalse(self.fixture.work.exists())
        self.assertEqual(self.client.get('/api/continuity/takes').json(), {'takes': []})
        self.assertFalse(self.fixture.work.exists())

    def test_public_metadata_and_reload_are_frozen_not_runtime_claims(self):
        self.imported()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['take']['take_id'], self.fixture.take_id)
        self.assertEqual(data['take']['integrity'], 'frozen_metadata_only')
        self.assertEqual(data['take']['runtime_compatibility'], 'unproven')
        self.assertEqual(data['media_url'], self.url + '/media')
        self.assertEqual(data['capsule_url'], self.url + '/capsule')
        for secret in ('/private', 'SECRET', 'unit.invalid', str(self.fixture.root),
                       'SyntheticTest', 'capture.private.json'):
            self.assertNotIn(secret, response.text)
        entries = self.client.get('/api/continuity/takes').json()['takes']
        self.assertEqual(entries, [data])
        fresh = FastAPI()
        fresh.include_router(api.create_router(lambda: self.fixture.work))
        with TestClient(fresh) as client:
            self.assertEqual(client.get(self.url).json(), data)

    def test_poster_is_a_safe_image_not_the_raw_native_video(self):
        self.imported()
        poster = self.fixture.root / 'poster.jpg'
        poster.write_bytes(b'\xff\xd8\xffsynthetic-poster')
        with patch.object(api, 'prepare_poster', return_value=poster, create=True) as prepare:
            response = self.client.get(self.url + '/poster')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['content-type'], 'image/jpeg')
        self.assertEqual(response.content, poster.read_bytes())
        prepare.assert_called_once()
        self.fixture.rewrite('take.cond.safetensors', b'corrupt')
        self.assertEqual(self.client.get(self.url + '/poster').status_code, 409)

    def test_readiness_is_separate_from_metadata_and_never_submits(self):
        self.imported()
        response = self.client.get(self.url + '/readiness')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['verified'])
        # Synthetic fixture has no saved audio phase; do not guess timing.
        self.assertFalse(response.json()['extend'])
        self.assertEqual(response.json()['reason_code'], 'timing_unavailable')
        self.fixture.rewrite('take.cond.safetensors', b'corrupt')
        response = self.client.get(self.url + '/readiness')
        self.assertFalse(response.json()['verified'])
        self.assertFalse(response.json()['extend'])
        self.assertEqual(response.json()['reason_code'], 'state_unverified')
        self.assertNotIn(str(self.fixture.work), response.text)

    def test_media_uses_complete_fresh_validation_and_supports_ranges(self):
        self.imported()
        with patch.object(api, 'get_validated_family', wraps=fixtures.ct.get_validated_family) as validate:
            response = self.client.get(self.url + '/media', headers={'Range': 'bytes=0-15'})
            self.assertEqual(response.status_code, 206, response.text)
            validate.assert_called_once_with(self.fixture.work, self.fixture.take_id)
        self.assertEqual(response.content, self.fixture.video.read_bytes()[:16])
        self.assertEqual(response.headers['content-type'], 'video/mp4')
        self.assertTrue(response.headers['content-disposition'].startswith('inline;'))
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        download = self.client.get(self.url + '/media?download=true')
        self.assertTrue(download.headers['content-disposition'].startswith('attachment;'))
        self.assertEqual(download.content, self.fixture.video.read_bytes())

    def test_corrupt_state_blocks_video_even_when_metadata_still_exists(self):
        self.imported()
        self.fixture.rewrite('take.cond.safetensors', b'corrupt')
        self.assertEqual(self.client.get(self.url).status_code, 200)
        response = self.client.get(self.url + '/media')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn(str(self.fixture.work), response.text)
        self.assertNotIn('take.cond.safetensors', response.text)

    def test_missing_native_state_is_conflict_not_a_pixel_fallback(self):
        self.imported()
        self.fixture.directory.chmod(0o700)
        (self.fixture.directory / 'take.mctx.safetensors').unlink()
        self.assertEqual(self.client.get(self.url + '/media').status_code, 409)

    def test_public_capsule_has_valid_original_schema_not_transport_annotations(self):
        self.imported()
        response = self.client.get(self.url + '/capsule?download=true')
        self.assertEqual(response.status_code, 200, response.text)
        capsule = response.json()
        fixtures.ct._validate_capsule(capsule, self.fixture.take_id)
        self.assertNotIn('integrity', capsule)
        self.assertNotIn('media_url', capsule)
        self.assertNotIn('/private', response.text)
        self.assertTrue(response.headers['content-disposition'].startswith('attachment;'))
        self.assertEqual(response.headers['x-opengenjutsu-integrity'], 'frozen-metadata-only')

    def test_invalid_missing_and_storage_failures_are_sanitized(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(self.url + '/media').status_code, 404)
        for bad in ('bad', 'A' * 32, 'a' * 31):
            self.assertEqual(self.client.get('/api/continuity/takes/' + bad).status_code, 422)
        with patch.object(api, 'list_takes', side_effect=PermissionError('/private/SECRET')):
            response = self.client.get('/api/continuity/takes')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('SECRET', response.text)
        self.imported()
        self.fixture.rewrite('capsule.json', b'{broken')
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assertEqual(self.client.get('/api/continuity/takes').status_code, 409)

    def test_real_preview_does_not_publish_the_embedded_private_execution_graph(self):
        import hashlib
        import json
        import subprocess
        from media_probe import probe_mp4
        from tests.test_timeline_artifact_contract import tensor_file
        graph = json.dumps(self.fixture.graph)
        # Real CPU-generated MP4; native tensor envelopes remain synthetic fixtures.
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi',
            '-i', 'color=blue:size=32x32:rate=24', '-frames:v', '5', '-threads', '1',
            '-c:v', 'libx264', '-metadata', 'prompt=' + graph,
            '-metadata', 'comment=SECRET_CAPTURE', '-metadata:s:v', 'handler_name=SECRET_HANDLER',
            '-movflags', '+use_metadata_tags', str(self.fixture.video)], check=True,
            capture_output=True)
        source = self.fixture.video.read_bytes()
        self.assertIn(b'SECRET', source, 'Guard fixture must really embed private metadata')
        self.fixture.meta['self_id'] = hashlib.sha256(source).hexdigest()
        self.fixture.write_mctx()
        structure = json.dumps({'__list__': [{'__list__': [
            {'__tensor__': 'embedding'}, {'__dict__': {}}]}]}).encode()
        self.fixture.cond.write_bytes(tensor_file({
            'embedding': ('F32', [1, 2, 3], None),
            'structure': ('U8', [len(structure)], structure)},
            {'format': 'obvpm_cond_v1', 'self_id': self.fixture.meta['self_id']}))
        self.imported()
        self.preview_double.stop()
        response = self.client.get(self.url + '/media')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(b'SECRET', response.content)
        self.assertNotIn(b'/private', response.content)
        destination = self.fixture.root / 'safe-preview.mp4'
        destination.write_bytes(response.content)
        geometry = probe_mp4(destination)
        self.assertEqual((geometry['frames'], geometry['width'], geometry['height']), (5, 32, 32))
        self.assertEqual(self.fixture.video.read_bytes(), source, 'Native source must stay byte-identical')
        self.assertEqual(response.headers['x-opengenjutsu-media'], 'metadata-stripped-preview')

    def test_no_browser_import_deletion_or_private_evidence_routes(self):
        self.imported()
        original = self.fixture.video.read_bytes()
        for method in ('post', 'patch', 'put', 'delete'):
            response = getattr(self.client, method)(self.url)
            self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.post('/api/continuity/takes', json={
            'path': '/private/anything.mp4'}).status_code, 405)
        for suffix in ('capture.private.json', 'mctx', 'conditioning'):
            self.assertEqual(self.client.get(self.url + '/' + suffix).status_code, 404)
        self.assertEqual(self.fixture.video.read_bytes(), original)
        self.assertFalse((self.fixture.work / 'jobs').exists())
