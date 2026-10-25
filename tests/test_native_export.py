"""Real CPU export from synthetic native envelopes, never H3 inference."""
import array
import hashlib
import json
import subprocess
import time
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import continuable_take as ct
from tests.test_timeline_artifact_contract import tensor_file
from test_timeline_store import IsolatedTimeline, make_video
from timeline_models import EditNativeWorkspace
from timeline_store import TimelineError, atomic_json, read_json
from timeline_export import ExportManager
from timeline_api import create_router
from media_probe import probe_mp4


class NativeExportTests(IsolatedTimeline):
    def family(self, take_id, color='black', frames=5, audio=False, private_metadata=False, source_job=None):
        source = self.work / ('source-' + take_id)
        source.mkdir()
        video = make_video(source / 'source.mp4', color=color, frames=frames,
                           fps='24', size='32x32', audio=audio)
        if private_metadata:
            tagged = source / 'tagged.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-c', 'copy',
                '-metadata', 'comment=PRIVATE_NATIVE_EXPORT_MARKER', str(tagged)],
                capture_output=True, check=True, timeout=30)
            video = tagged
        sha = hashlib.sha256(video.read_bytes()).hexdigest()
        metadata = {'format': 'mctx_v1', 'self_id': sha, 'width': '32',
                    'height': '32', 'fps': '24', 'raw_frames': '9',
                    'delivered_frames': str(frames)}
        mctx = source / 'source.mctx.safetensors'
        mctx.write_bytes(tensor_file({'video': ('F16', [1, 24, 3, 2, 2], None),
                                     'audio': ('F16', [1, 32, 2, 5], None)}, metadata))
        structure = json.dumps({'__list__': [{'__list__': [
            {'__tensor__': 'embedding'}, {'__dict__': {}}]}]}).encode()
        cond = source / 'source.cond.safetensors'
        cond.write_bytes(tensor_file({'embedding': ('F32', [1, 2, 3], None),
            'structure': ('U8', [len(structure)], structure)},
            {'format': 'obvpm_cond_v1', 'self_id': sha}))
        ct.import_family(video, mctx, cond, root=source, work=self.work,
                         take_id=take_id, captured_graph=None, source_job=source_job, operator_label='synthetic-export-only')
        return ct.get_validated_family(self.work, take_id)

    def project(self, takes):
        project = self.store.create('Native path')
        placements = [{'placement_id': f'{i + 1:032x}', 'take_id': take}
                      for i, take in enumerate(takes)]
        return self.store.edit_native_workspace(project['project_id'], EditNativeWorkspace(
            revision=0, placements=placements, selected_placement_id=None, drafts={}))

    def manager(self):
        manager = ExportManager(self.store)
        self.addCleanup(manager.close)
        return manager

    def finish(self, manager, result):
        end = time.monotonic() + 30
        while result['status'] in ('queued', 'running') and time.monotonic() < end:
            time.sleep(.02)
            result = manager.get(result['export_id'])
        self.assertEqual(result['status'], 'ready', result)
        return result

    def test_native_snapshot_owns_persisted_order_repeated_takes_and_no_drafts(self):
        a, b = 'a' * 32, 'b' * 32
        self.family(a)
        self.family(b, 'white', 7)
        project = self.project([a, b, a])
        path = self.store._path('projects', project['project_id'])
        before = path.read_bytes(), path.stat().st_mtime_ns
        with patch.object(self.store, '_public', side_effect=AssertionError('No legacy projection')):
            snapshot = self.store.native_snapshot(project['project_id'], 1)
        self.assertEqual(snapshot['source'], 'native')
        self.assertEqual([s['take_id'] for s in snapshot['segments']], [a, b, a])
        self.assertEqual([s['placement_id'] for s in snapshot['segments']],
                         [p['placement_id'] for p in project['placements']])
        self.assertEqual([s['out_frame'] for s in snapshot['segments']], [5, 7, 5])
        self.assertEqual(set(snapshot['assets']), {a, b})
        self.assertNotIn('clips', snapshot['project'])
        self.assertNotIn('drafts', snapshot['project'])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.store.edit_native_workspace(project['project_id'], EditNativeWorkspace(
            revision=1, placements=[], selected_placement_id=None, drafts={}))
        self.assertEqual(len(snapshot['segments']), 3)

    def test_revision_conflict_precedes_any_native_validation(self):
        project = self.store.create('Empty')
        with patch.object(ct, 'get_validated_family', side_effect=AssertionError('No media work')):
            with self.assertRaises(TimelineError) as conflict:
                self.store.native_snapshot(project['project_id'], 1)
        self.assertEqual(conflict.exception.status_code, 409)

    def test_empty_native_path_does_not_export_hidden_legacy_clips(self):
        project, _ = self.imported()
        with self.assertRaises(TimelineError) as error:
            self.store.native_snapshot(project['project_id'], project['revision'])
        self.assertEqual(error.exception.status_code, 422)

    def test_each_changed_native_family_role_is_refused_without_project_mutation(self):
        for index, role in enumerate(('video', 'mctx', 'conditioning')):
            with self.subTest(role=role):
                take_id = f'{index + 10:032x}'
                family = self.family(take_id)
                project = self.project([take_id])
                path = self.store._path('projects', project['project_id'])
                before = path.read_bytes()
                artifact = getattr(family, role)
                artifact.chmod(0o600)
                artifact.write_bytes(b'changed')
                with self.assertRaises(TimelineError) as error:
                    self.store.native_snapshot(project['project_id'], 1)
                self.assertEqual(error.exception.status_code, 409)
                self.assertNotIn(str(self.work), str(error.exception))
                self.assertEqual(path.read_bytes(), before)

    def test_real_native_render_order_frames_audio_and_source_separated_dedupe(self):
        a, b = 'a' * 32, 'b' * 32
        self.family(a, audio=True)
        self.family(b, 'white', 7)
        project = self.project([a, b, a])
        # A real legacy cut coexists in the very same revision; no conversion.
        video = make_video(self.media / 'legacy.mp4', color='red')
        self.store.import_job(project['project_id'], 1, self.job(video).id)
        manager = self.manager()
        native = manager.submit(project['project_id'], 2, source='native')
        self.assertEqual(native['source'], 'native')
        self.assertEqual(native['placement_ids'], [p['placement_id'] for p in project['placements']])
        self.assertIsNone(native['preview_url'])
        self.assertIsNone(native['download_url'])
        self.assertIsNone(native['error'])
        legacy = manager.submit(project['project_id'], 2)
        self.assertNotEqual(native['export_id'], legacy['export_id'])
        native = self.finish(manager, native)
        self.finish(manager, legacy)
        path = manager.media(native['export_id'])
        self.assertEqual(probe_mp4(path)['frames'], 17)
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        stride = 32 * 32 * 3
        for i in range(17):
            pixel = raw[i * stride + (16 * 32 + 16) * 3]
            self.assertGreater(pixel, 240) if 5 <= i < 12 else self.assertLess(pixel, 10)
        audio = array.array('f', subprocess.check_output(['ffmpeg', '-v', 'error',
            '-i', str(path), '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-']))
        def energy(start, end):
            samples = audio[round(start * 48000):round(end * 48000)]
            return sum(v * v for v in samples) / len(samples)
        self.assertGreater(energy(.04, .14), .001)
        self.assertLess(energy(.32, .44), .00001)
        self.assertGreater(energy(.56, .66), .001)
        manager.close()
        fresh = self.manager()
        self.assertEqual(fresh.submit(project['project_id'], 2, source='native')['export_id'], native['export_id'])
        self.assertEqual(fresh.submit(project['project_id'], 2)['export_id'], legacy['export_id'])
        self.assertEqual(fresh.media(native['export_id']).read_bytes(), path.read_bytes())

    def test_edit_during_native_probe_conflicts_without_queuing(self):
        take = 'a' * 32
        self.family(take)
        project = self.project([take])
        from timeline_store import inspect_mp4
        def edit_during_probe(path):
            self.store.edit_native_workspace(project['project_id'], EditNativeWorkspace(
                revision=1, placements=[], selected_placement_id=None, drafts={}))
            return inspect_mp4(path)
        with patch('timeline_store.inspect_mp4', side_effect=edit_during_probe):
            with self.assertRaises(TimelineError) as error:
                self.manager().submit(project['project_id'], 1, source='native')
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(list((self.store.root / 'exports').iterdir()), [])

    def test_native_output_drops_private_container_metadata(self):
        take = 'a' * 32
        self.family(take, private_metadata=True)
        project = self.project([take])
        manager = self.manager()
        result = self.finish(manager, manager.submit(project['project_id'], 1, source='native'))
        tags = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
            'format_tags:stream_tags', '-of', 'json', str(manager.media(result['export_id']))])
        self.assertNotIn(b'PRIVATE_NATIVE_EXPORT_MARKER', tags)

    def test_native_sidecar_changed_during_render_prevents_publication(self):
        take = 'a' * 32
        family = self.family(take)
        project = self.project([take])
        import timeline_export
        original = timeline_export._ffmpeg
        changed = False
        def mutate_after_decode(*args, **kwargs):
            nonlocal changed
            original(*args, **kwargs)
            if not changed:
                changed = True
                family.conditioning.chmod(0o600)
                family.conditioning.write_bytes(b'changed during render')
        manager = self.manager()
        with patch.object(timeline_export, '_ffmpeg', side_effect=mutate_after_decode):
            result = manager.submit(project['project_id'], 1, source='native')
            end = time.monotonic() + 30
            while result['status'] in ('queued', 'running') and time.monotonic() < end:
                time.sleep(.02)
                result = manager.get(result['export_id'])
        self.assertEqual(result['status'], 'error')
        self.assertIsNone(result['preview_url'])
        self.assertFalse(self.store._path('exports', result['export_id'], 'video.mp4').exists())

    def test_native_route_strict_payload_revision_urls_and_ready_range(self):
        take = 'a' * 32
        self.family(take)
        project = self.project([take])
        app = FastAPI()
        app.include_router(create_router(lambda: self.work, lambda: self.media, 2_000_000))
        with TestClient(app) as client:
            url = f"/api/timeline/projects/{project['project_id']}/native-workspace/export"
            for payload in ({'revision': True}, {'revision': '1'}, {'revision': 1, 'placement_ids': []},
                            {'revision': 1, 'source': 'legacy'}, {'revision': 1, 'path': '/private'}):
                self.assertEqual(client.post(url, json=payload).status_code, 422)
            self.assertEqual(client.post(url, json={'revision': 0}).status_code, 409)
            response = client.post(url, json={'revision': 1})
            self.assertEqual(response.status_code, 202, response.text)
            result = response.json()
            self.assertEqual(result['source'], 'native')
            self.assertIsNone(result['preview_url'])
            self.assertNotIn(str(self.work), response.text)
            for _ in range(200):
                result = client.get(result['status_url']).json()
                if result['status'] not in ('queued', 'running'):
                    break
                time.sleep(.02)
            self.assertEqual(result['status'], 'ready', result)
            self.assertEqual(client.post(url, json={'revision': 1}).status_code, 200)
            media = client.get(result['download_url'], headers={'Range': 'bytes=0-7'})
            self.assertEqual(media.status_code, 206)
            self.assertTrue(media.headers['content-disposition'].startswith('attachment;'))
