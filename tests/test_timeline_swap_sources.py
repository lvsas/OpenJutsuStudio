"""Explicit Swap placements: isolated records, synthetic CPU media, no GPU."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import subprocess
import time
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import continuable_take as ct
import test_native_export as native_fixtures
from test_timeline_store import IsolatedTimeline, make_video
from timeline_api import create_router
from timeline_export import ExportManager, render_snapshot
from timeline_models import EditNativeWorkspace, NativePlacement
from timeline_store import TimelineError, TimelineStore, atomic_json, read_json
from media_probe import probe_mp4


class TimelineSwapSourceTests(IsolatedTimeline):
    family = native_fixtures.NativeExportTests.family

    def placement(self, take_id, kind='swap'):
        row = {'placement_id': uuid.uuid4().hex, 'take_id': take_id}
        if kind != 'native':
            row['source_kind'] = kind
        return row

    def save(self, project, placements, revision=None):
        return self.store.edit_native_workspace(project['project_id'], EditNativeWorkspace(
            revision=project['revision'] if revision is None else revision,
            placements=placements, selected_placement_id=None, drafts={}))

    def video_job(self, engine='minimax-h3', **options):
        video = make_video(self.media / (uuid.uuid4().hex + '.mp4'), fps='24', **options)
        return self.job(video, engine)

    def files(self):
        return {p.relative_to(self.work): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.work.rglob('*') if p.is_file()}

    def finish(self, manager, result):
        deadline = time.monotonic() + 30
        while result['status'] in ('queued', 'running') and time.monotonic() < deadline:
            time.sleep(.02)
            result = manager.get(result['export_id'])
        return result

    def test_placement_default_serialization_and_strict_kind(self):
        row = self.placement('a' * 32, 'native')
        value = NativePlacement(**row)
        self.assertEqual(value.source_kind, 'native')
        self.assertEqual(value.model_dump(), row)
        self.assertEqual(json.loads(value.model_dump_json()), row)
        self.assertEqual(NativePlacement(**row, source_kind='native').model_dump(), row)
        swap = self.placement('a' * 32)
        self.assertEqual(NativePlacement(**swap).model_dump(), swap)
        for kind in ('upload', '', None, True):
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                NativePlacement(**row, source_kind=kind)

    def test_both_engines_explicit_cross_project_reuse_remove_reopen_membership(self):
        origin = self.store.create('Origin')
        target = self.store.create('Target')
        for engine in ('minimax-h3', 'ltx25-ripple'):
            job = self.video_job(engine)
            job.meta['origin_project_id'] = origin['project_id']
            job.save()
            row = self.placement(job.id)
            before = job.path.read_bytes()
            with patch('continuable_take.get_take', side_effect=AssertionError('Not a native Take')), \
                    patch('timeline_store.inspect_mp4', side_effect=AssertionError('No decode on save')):
                target = self.save(target, [row])
                self.assertEqual(target['placements'], [row])
                self.assertEqual(self.store.get_assets(target['project_id'])['assets']['takes'], [])
                self.assertIn(job.id, self.store.get_assets(target['project_id'])['assets']['jobs'])
                self.assertEqual(self.store.get_native_workspace(origin['project_id'])['placements'], [])
                target = self.save(target, [])
            fresh = TimelineStore(self.work, self.media, 2_000_000)
            self.assertEqual(fresh.get_native_workspace(target['project_id'])['placements'], [])
            self.assertIn(job.id, fresh.get_assets(target['project_id'])['assets']['jobs'])
            self.assertEqual(job.path.read_bytes(), before)
            self.assertEqual(list((self.store.root / 'takes').iterdir()), [])

    def test_kind_collision_keeps_distinct_memberships_and_does_not_resolve_job_as_take(self):
        take_id = 'c' * 32
        self.family(take_id)
        job = self.video_job('ltx25-ripple')
        job.path.unlink()
        job.id = take_id
        job.save()
        rows = [self.placement(take_id, 'native'), self.placement(take_id)]
        project = self.save(self.store.create('Collision'), rows)
        self.assertEqual(project['placements'], rows)
        assets = self.store.get_assets(project['project_id'])['assets']
        self.assertEqual(assets['takes'], [take_id])
        self.assertEqual(assets['jobs'], [take_id])
        project = self.save(project, [])
        self.assertEqual(self.store.get_assets(project['project_id'])['assets'], assets)

    def test_invalid_unfinished_unsafe_or_missing_result_does_not_write(self):
        project = self.store.create('No changes')
        valid = self.video_job()
        outside = make_video(self.work / 'outside.mp4')
        linked = self.media / 'linked.mp4'
        linked.symlink_to(valid.result)
        escape = self.media / 'escape'
        escape.symlink_to(self.work, target_is_directory=True)
        empty = self.media / 'empty.mp4'
        empty.touch()
        cases = [('minimax-h3', 'running', valid.result), ('ltx25-ripple', 'error', valid.result),
                 ('flux3-klein-character', 'done', valid.result), ('minimax-h3', 'done', None),
                 ('ltx25-ripple', 'done', str(outside)), ('minimax-h3', 'done', str(linked)),
                 ('minimax-h3', 'done', str(escape / 'outside.mp4')),
                 ('ltx25-ripple', 'done', str(self.media / 'absent.mp4')),
                 ('minimax-h3', 'done', str(self.media)), ('minimax-h3', 'done', str(empty))]
        path = self.store._path('projects', project['project_id'])
        before = path.read_bytes()
        for engine, status, result in cases:
            with self.subTest(engine=engine, status=status, result=result):
                job = self.job(result, engine, status)
                if result is None:
                    job.result = None
                    job.save()
                with self.assertRaises(TimelineError) as error:
                    self.save(project, [self.placement(job.id)])
                self.assertIn(error.exception.status_code, (404, 409, 422))
                self.assertNotIn(str(self.work), str(error.exception))
                self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(TimelineError) as error:
            self.save(project, [self.placement('f' * 32)])
        self.assertEqual(error.exception.status_code, 404)

    def test_revision_conflict_precedes_swap_lookup(self):
        project = self.store.create('Revision')
        with patch.object(self.store, '_job', side_effect=AssertionError('No lookup')):
            with self.assertRaises(TimelineError) as error:
                self.save(project, [self.placement('a' * 32)], revision=1)
        self.assertEqual(error.exception.status_code, 409)

    def test_library_linkage_is_validated_metadata_only_and_gets_never_write(self):
        valid = self.video_job()
        take_id = 'd' * 32
        # The frozen origin binds a linkage to THIS application job.
        family = self.family(take_id, source_job=valid.id)
        valid.meta.update(native_take_id=take_id, private_prompt='PRIVATE_SECRET')
        valid.prompt = 'PRIVATE_PROMPT'
        valid.save()
        wrong = self.video_job()
        wrong.meta['native_take_id'] = take_id
        wrong.save()
        absent = self.video_job('ltx25-ripple')
        absent.meta['native_take_id'] = 'e' * 32
        absent.save()
        malformed = self.video_job()
        malformed.meta['native_take_id'] = '../private'
        malformed.save()
        project = self.save(self.store.create('Read only'), [self.placement(valid.id)])
        # A library link is not a fresh family/integrity/capability guarantee.
        family.conditioning.chmod(0o600)
        family.conditioning.write_bytes(b'changed sidecar')
        before = self.files()
        app = FastAPI()
        app.include_router(create_router(lambda: self.work, lambda: self.media, 2_000_000))
        with TestClient(app) as client, \
                patch('timeline_store.inspect_mp4', side_effect=AssertionError('No probing')), \
                patch('timeline_store.subprocess.run', side_effect=AssertionError('No subprocess')), \
                patch('continuable_take.get_validated_family', side_effect=AssertionError('No full family validation')), \
                patch.object(self.store, '_save_edit', side_effect=AssertionError('No mutation')):
            for _ in range(2):
                response = client.get('/api/timeline/library')
                self.assertEqual(response.status_code, 200, response.text)
                rows = {row['job_id']: row for row in response.json()['jobs']}
                self.assertEqual(rows[valid.id]['native_take_id'], take_id)
                for job in (wrong, absent, malformed):
                    self.assertNotIn('native_take_id', rows[job.id])
                self.assertEqual(set(rows[valid.id]), {'job_id', 'engine', 'status', 'created', 'native_take_id'})
                self.assertNotIn('PRIVATE', response.text)
                self.assertNotIn(str(self.work), response.text)
                for suffix in ('native-workspace', 'assets'):
                    self.assertEqual(client.get(f"/api/timeline/projects/{project['project_id']}/{suffix}").status_code, 200)
        self.assertEqual(self.files(), before)

    def test_snapshot_collision_free_identity_and_real_mixed_render_preserve_native(self):
        take_id = 'a' * 32
        self.family(take_id, frames=5, audio=True)
        job = self.video_job('ltx25-ripple', color='white', frames=7, size='32x32')
        job.path.unlink()
        job.id = take_id
        job.save()
        rows = [self.placement(take_id, 'native'), self.placement(job.id), self.placement(job.id)]
        project = self.save(self.store.create('Mixed'), rows)
        before = self.files()
        snapshot = self.store.native_snapshot(project['project_id'], 1)
        self.assertEqual(self.files(), before)
        self.assertEqual(len(snapshot['assets']), 2)
        self.assertIn(take_id, snapshot['assets'])  # Old native snapshots remain readable.
        swap = snapshot['assets']['swap:' + take_id]
        self.assertEqual(swap['job_id'], job.id)
        self.assertEqual(swap['engine'], 'ltx25-ripple')
        self.assertEqual(len(swap['sha256']), 64)
        self.assertGreater(swap['size_bytes'], 0)
        self.assertEqual(len(swap['identity']), 5)
        self.assertNotIn('capsule_sha256', swap)
        self.assertEqual([s['out_frame'] for s in snapshot['segments']], [5, 7, 7])
        self.assertEqual(snapshot['segments'][1]['source_kind'], 'swap')
        self.assertNotIn('source_kind', snapshot['segments'][0])
        manager = ExportManager(self.store)
        self.addCleanup(manager.close)
        result = manager.submit(project['project_id'], 1, source='native')
        self.save(project, [])
        result = self.finish(manager, result)
        self.assertEqual(result['status'], 'ready', result)
        output = manager.media(result['export_id'])
        self.assertEqual(probe_mp4(output)['frames'], 19)
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(output),
                                      '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        stride = 32 * 32 * 3
        for i in range(19):
            pixel = raw[i * stride + (16 * 32 + 16) * 3]
            self.assertLess(pixel, 10) if i < 5 else self.assertGreater(pixel, 240)
        persisted = read_json(self.store._path('exports', result['export_id'], 'snapshot.json'))
        self.assertEqual(persisted, snapshot)

    def test_swap_exact_fps_rejected_and_changed_result_revalidated(self):
        self.family('a' * 32)
        job = self.video_job()
        project = self.save(self.store.create('Integrity'),
                            [self.placement('a' * 32, 'native'), self.placement(job.id)])
        snapshot = self.store.native_snapshot(project['project_id'], 1)
        # Retargeting a completed job to even an identical hardlink is a change.
        alternate = self.media / 'alternate.mp4'
        alternate.hardlink_to(job.result)
        job.result = str(alternate)
        job.save()
        with self.assertRaises(TimelineError):
            render_snapshot(self.store, snapshot, self.work / 'unpublished.mp4')
        self.assertFalse((self.work / 'unpublished.mp4').exists())
        other = self.job(make_video(self.media / 'different-rate.mp4', fps='30000/1001'))
        project = self.save(project, [self.placement('a' * 32, 'native'), self.placement(other.id)])
        with self.assertRaises(TimelineError) as error:
            self.store.native_snapshot(project['project_id'], project['revision'])
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn('no silent FPS conversion', error.exception.detail)

    def test_swap_changes_before_or_during_render_never_publish(self):
        import timeline_export
        for mutation in ('bytes', 'status', 'engine', 'missing', 'symlink', 'during'):
            with self.subTest(mutation=mutation):
                job = self.video_job(frames=5)
                project = self.save(self.store.create('Frozen'), [self.placement(job.id)])
                snapshot = self.store.native_snapshot(project['project_id'], 1)
                output = self.work / (mutation + '.mp4')
                source = Path(job.result)
                original = timeline_export._ffmpeg
                def mutate_after_decode(*args, **kwargs):
                    original(*args, **kwargs)
                    job.status = 'error'
                    job.save()
                if mutation == 'bytes':
                    source.write_bytes(b'changed')
                elif mutation in ('status', 'engine'):
                    setattr(job, mutation, 'error' if mutation == 'status' else 'ltx25-ripple')
                    job.save()
                elif mutation == 'missing':
                    source.unlink()
                elif mutation == 'symlink':
                    moved = source.with_suffix('.moved.mp4')
                    source.rename(moved)
                    source.symlink_to(moved)
                with patch.object(timeline_export, '_ffmpeg', side_effect=(
                        mutate_after_decode if mutation == 'during' else original)):
                    with self.assertRaises(TimelineError):
                        render_snapshot(self.store, snapshot, output)
                self.assertFalse(output.exists())

    def test_edit_during_swap_inspection_conflicts_before_export_queue(self):
        job = self.video_job()
        project = self.save(self.store.create('Late revision'), [self.placement(job.id)])
        from timeline_store import inspect_mp4
        def concurrent_edit(path):
            self.save(project, [])
            return inspect_mp4(path)
        with patch('timeline_store.inspect_mp4', side_effect=concurrent_edit):
            with self.assertRaises(TimelineError) as error:
                self.store.native_snapshot(project['project_id'], 1)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(list((self.store.root / 'exports').iterdir()), [])
