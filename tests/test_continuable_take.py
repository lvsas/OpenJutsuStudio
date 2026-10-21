"""Synthetic envelope fixtures only: not H3 tensor/runtime or GPU proof."""
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from tests.test_timeline_artifact_contract import tensor_file
import continuable_take as ct


class ContinuableTakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'sources'
        self.root.mkdir()
        self.work = Path(self.tmp.name) / 'isolated-work'
        self.take_id = 'a' * 32
        self.parent = 'b' * 64
        self.video = self.root / 'arbitrary.mp4'
        self.mctx = self.root / 'different.mctx.safetensors'
        self.cond = self.root / 'explicit.cond.safetensors'
        self.video.write_bytes(b'SYNTHETIC MP4: probe mocked, not a real render')
        self.meta = {
            'format': 'mctx_v1', 'self_id': hashlib.sha256(self.video.read_bytes()).hexdigest(),
            'width': '32', 'height': '32', 'fps': '24', 'raw_frames': '9',
            'delivered_frames': '5', 'parent_id': self.parent, 'relation': 'extends',
            'parent_grade': 'latent', 'parent_join_frame': '273',
            'pinned_head_frames': '3', 'pinned_tail_frames': '0', 'overlap_frames': '0',
            'pins': json.dumps([{'source_id': self.parent, 'source_path': '/private/secret.mp4',
                                 'source_start': 238, 'source_frames': 39, 'place': 'before',
                                 'handover_edge': True, 'mode': 'masked'}]),
        }
        self.write_mctx()
        structure = json.dumps({'__list__': [{'__list__': [
            {'__tensor__': 'embedding'}, {'__dict__': {}}]}]}).encode()
        self.cond.write_bytes(tensor_file({
            'embedding': ('F32', [1, 2, 3], None),
            'structure': ('U8', [len(structure)], structure)},
            {'format': 'obvpm_cond_v1', 'self_id': self.meta['self_id']}))
        self.graph = {'7': {'class_type': 'SyntheticTest', 'inputs': {
            'filename': '/private/captured.mp4', 'url': 'https://unit.invalid/?token=SECRET'}}}
        self.probe = patch('timeline_artifacts.probe_mp4', return_value={
            'width': 32, 'height': 32, 'fps': 24.0, 'frames': 5})
        self.probe.start()
        self.addCleanup(self.probe.stop)

    def write_mctx(self):
        self.mctx.write_bytes(tensor_file({
            'video': ('F16', [1, 24, 3, 2, 2], None),
            'audio': ('F16', [1, 32, 2, 5], None)}, self.meta))

    def do_import(self, **overrides):
        args = dict(root=self.root, work=self.work, take_id=self.take_id,
                    captured_graph=self.graph, graph_completeness='complete',
                    source_job='2218', operator_label='synthetic-proof')
        args.update(overrides)
        return ct.import_family(self.video, self.mctx, self.cond, **args)

    @property
    def directory(self):
        return self.work / 'timeline' / 'continuable-takes' / self.take_id

    def rewrite(self, name, value):
        path = self.directory / name
        path.chmod(0o600)
        path.write_bytes(value)

    def test_publication_syncs_file_entries_before_visibility_and_store_after(self):
        import stat
        events = []
        original = os.fsync
        def sync(fd):
            path = Path(os.readlink('/proc/self/fd/' + str(fd)))
            events.append((path, stat.S_ISDIR(os.fstat(fd).st_mode), self.directory.exists()))
            original(fd)
        with patch.object(ct.os, 'fsync', side_effect=sync):
            self.do_import()
        staged = [(index, path, visible) for index, (path, directory, visible)
                  in enumerate(events) if directory and path.name.endswith('.part')]
        self.assertEqual(len(staged), 1, 'Staging directory entries need an explicit fsync')
        index, staging, visible = staged[0]
        self.assertFalse(visible)
        files = {path.name for path, directory, _ in events[:index]
                 if not directory and path.parent == staging}
        self.assertEqual(files, {'take.mp4', 'take.mctx.safetensors',
            'take.cond.safetensors', 'capsule.json', 'capture.private.json'})
        self.assertIn((self.directory.parent, True, True), events[index + 1:])

    def test_new_registry_ancestor_entries_are_synced(self):
        import stat
        directories = []
        original = os.fsync
        def sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                directories.append(Path(os.readlink('/proc/self/fd/' + str(fd))))
            original(fd)
        with patch.object(ct.os, 'fsync', side_effect=sync):
            self.do_import()
        for parent in (self.work.parent, self.work, self.work / 'timeline'):
            self.assertIn(parent, directories, 'New directory entry must be synced in its parent')

    def test_staging_directory_sync_failure_publishes_nothing(self):
        import errno
        import stat
        original = os.fsync
        def sync(fd):
            if (stat.S_ISDIR(os.fstat(fd).st_mode)
                    and Path(os.readlink('/proc/self/fd/' + str(fd))).name.endswith('.part')):
                raise OSError(errno.ENOSPC, 'Injected directory sync failure')
            original(fd)
        with patch.object(ct.os, 'fsync', side_effect=sync):
            with self.assertRaises(OSError):
                self.do_import()
        self.assertFalse(self.directory.exists())
        self.assertEqual(list(self.directory.parent.iterdir()), [])

    def test_post_publication_sync_failure_preserves_visible_complete_take(self):
        import errno
        import stat
        store = ct._store(self.work, create=True)
        original = os.fsync
        def sync(fd):
            if (stat.S_ISDIR(os.fstat(fd).st_mode)
                    and Path(os.readlink('/proc/self/fd/' + str(fd))) == store
                    and self.directory.exists()):
                raise OSError(errno.ENOSPC, 'Injected final directory sync failure')
            original(fd)
        with patch.object(ct.os, 'fsync', side_effect=sync):
            with self.assertRaises(OSError):
                self.do_import()
        # Failure to confirm durability is not permission to delete visible data.
        validated = ct.get_validated_family(self.work, self.take_id)
        self.assertEqual(validated.video.read_bytes(), self.video.read_bytes())
        self.assertEqual(list(store.iterdir()), [self.directory])

    def test_cli_returns_generated_id_when_final_publication_sync_is_uncertain(self):
        self._check_cli_generated_id_recovery()

    def test_cli_generated_id_survives_post_publication_cleanup_lookup_failure(self):
        self._check_cli_generated_id_recovery(fail_cleanup=True)

    def _check_cli_generated_id_recovery(self, *, fail_cleanup=False):
        import contextlib
        import errno
        import importlib.util
        import io
        import stat
        self.make_real_cpu_fixture()
        script = Path(__file__).resolve().parents[1] / 'scripts/import_h3_take.py'
        spec = importlib.util.spec_from_file_location('take_cli_uncertain_test', script)
        assert spec is not None and spec.loader is not None
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        original = os.fsync
        original_exists = Path.exists
        sync_failed = False
        def sync(fd):
            nonlocal sync_failed
            path = Path(os.readlink('/proc/self/fd/' + str(fd)))
            if (stat.S_ISDIR(os.fstat(fd).st_mode) and path.name == 'continuable-takes'
                    and any(p.name[0] != '.' for p in path.iterdir())):
                sync_failed = True
                raise OSError(errno.ENOSPC, '/private/SECRET final sync failed')
            original(fd)
        def exists(path):
            if fail_cleanup and sync_failed and path.name.endswith('.part'):
                raise OSError(errno.EIO, '/private/SECRET cleanup lookup failed')
            return original_exists(path)
        output, errors = io.StringIO(), io.StringIO()
        # Omit --take-id deliberately; recovery must reveal the generated ID.
        args = self.cli_args()[3:-2] + ['--embedded-prompt', '--graph-completeness', 'complete']
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
                patch.object(ct.os, 'fsync', side_effect=sync), \
                patch.object(Path, 'exists', new=exists):
            code = cli.main(args)
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), '')
        self.assertIn('publication_visible_durability_unconfirmed', errors.getvalue())
        notice = json.loads(errors.getvalue())
        self.assertRegex(notice['take_id'], r'^[0-9a-f]{32}$')
        self.assertNotIn('SECRET', errors.getvalue())
        self.assertNotIn(str(self.work), errors.getvalue())
        recovered = ct.get_validated_family(self.work, notice['take_id'])
        self.assertEqual(recovered.record.take_id, notice['take_id'])
        self.assertEqual(len(ct.list_takes(self.work)), 1)

    def test_library_preserves_generated_id_when_post_publish_readback_fails(self):
        with patch.object(ct, 'get_take', side_effect=OSError('/private/SECRET readback')):
            with self.assertRaises(OSError) as caught:
                self.do_import(take_id=None)
        error = caught.exception
        self.assertTrue(hasattr(error, 'take_id'), 'Published ID must survive a failed readback')
        assert isinstance(error, ct.TakePublicationUncertain)
        self.assertEqual(error.phase, 'readback')
        self.assertNotIn('SECRET', str(error))
        self.assertEqual(ct.get_validated_family(self.work, error.take_id).record.take_id, error.take_id)
        self.assertEqual(len(ct.list_takes(self.work)), 1)

    def test_cli_keeps_id_when_its_fresh_validation_fails_after_import(self):
        import contextlib
        import importlib.util
        import io
        self.make_real_cpu_fixture()
        script = Path(__file__).resolve().parents[1] / 'scripts/import_h3_take.py'
        spec = importlib.util.spec_from_file_location('take_cli_validation_test', script)
        assert spec is not None and spec.loader is not None
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
                patch.object(cli, 'get_validated_family', side_effect=OSError('/private/SECRET validation')):
            code = cli.main(self.cli_args()[3:-2] + ['--embedded-prompt'])
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), '')
        self.assertIn('publication_visible_validation_unconfirmed', errors.getvalue())
        notice = json.loads(errors.getvalue())
        self.assertNotIn('SECRET', errors.getvalue())
        self.assertEqual(ct.get_validated_family(self.work, notice['take_id']).record.take_id,
                         notice['take_id'])
        self.assertEqual(len(ct.list_takes(self.work)), 1)

    def test_success_frozen_record_and_fixed_private_copies(self):
        take = self.do_import()
        self.assertIsInstance(take, ct.TakeRecord)
        self.assertEqual(take.take_id, self.take_id)
        self.assertEqual(take.engine, 'H3OBVPM')
        with self.assertRaises(dataclasses.FrozenInstanceError):
            take.take_id = 'c' * 32
        self.assertEqual(set(p.name for p in self.directory.iterdir()), {
            'take.mp4', 'take.mctx.safetensors', 'take.cond.safetensors',
            'capsule.json', 'capture.private.json'})
        for source, name in ((self.video, 'take.mp4'), (self.mctx, 'take.mctx.safetensors'),
                             (self.cond, 'take.cond.safetensors')):
            self.assertEqual(source.read_bytes(), (self.directory / name).read_bytes())
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o500)
        self.assertEqual((self.directory / 'capture.private.json').stat().st_mode & 0o777, 0o400)
        self.assertEqual(ct.get_take(self.work, self.take_id), take)

    def test_native_lineage_and_raw_vs_delivered_preserved_not_inferred(self):
        record = self.do_import().to_manifest()
        self.assertEqual(record['lineage']['parent_id'], self.parent)
        self.assertEqual(record['lineage']['relation'], 'extends')
        self.assertEqual(record['lineage']['pins'][0]['source_start'], 238)
        self.assertEqual(record['lineage']['parent_join_frame'], '273')
        self.assertEqual(record['family']['context']['raw_frames'], 9)
        self.assertEqual(record['family']['context']['delivered_frames'], 5)
        self.assertNotIn('source_path', record['lineage']['pins'][0])
        evidence = json.loads((self.directory / 'capture.private.json').read_bytes())
        self.assertEqual(evidence['mctx_metadata'], self.meta)

    def test_public_metadata_contains_no_paths_secrets_or_graph(self):
        record = self.do_import()
        public = json.dumps(record.to_manifest())
        on_disk = (self.directory / 'capsule.json').read_text()
        for text in (public, on_disk):
            for secret in ('/private', 'SECRET', 'unit.invalid', str(self.root), 'filename'):
                self.assertNotIn(secret, text)
        public_record = record.to_manifest()
        public_record['lineage']['pins'].clear()
        self.assertEqual(len(record.to_manifest()['lineage']['pins']), 1)

    def test_recipe_execution_evidence_is_not_approved_replay(self):
        value = self.do_import().to_manifest()
        self.assertEqual(value['recipe']['availability'], 'captured_execution_graph')
        self.assertEqual(value['recipe']['completeness'], 'complete')
        self.assertEqual(value['recipe']['render_recipe'], 'unknown')
        self.assertEqual(value['recipe']['seeds'], 'unknown')
        self.assertEqual(value['recipe']['model_identities'], 'unknown')
        self.assertEqual(value['runtime_compatibility'], 'unproven')
        self.assertEqual(value['recipe']['app_replay'], 'unreviewed')
        self.assertNotIn('can_forward', value)

    def test_unknown_graph_completeness_not_defaulted_to_complete(self):
        recipe = self.do_import(graph_completeness='unknown').to_manifest()['recipe']
        self.assertEqual(recipe['completeness'], 'unknown')
        self.assertIsNotNone(recipe['graph_sha256'])

    def test_missing_recipe_is_explicit_not_synthesized(self):
        value = self.do_import(captured_graph=None, graph_completeness='unknown').to_manifest()
        self.assertEqual(value['recipe']['availability'], 'unavailable')
        self.assertIsNone(value['recipe']['graph_sha256'])
        self.assertEqual(value['recipe']['app_replay'], 'unavailable')

    def test_canonical_graph_digest_stable_and_bound_to_private_evidence(self):
        first = self.do_import()
        self.take_id = 'c' * 32
        second = self.do_import(captured_graph=json.loads(json.dumps(self.graph, sort_keys=True)))
        self.assertEqual(first.to_manifest()['recipe']['graph_sha256'],
                         second.to_manifest()['recipe']['graph_sha256'])
        validated = ct.get_validated_family(self.work, self.take_id)
        self.assertEqual(validated.record, second)
        self.assertEqual(validated.artifacts.context.raw_frames, 9)
        self.assertEqual(validated.video, self.directory / 'take.mp4')

    def test_missing_cond_publishes_nothing(self):
        self.cond.unlink()
        with self.assertRaises((ValueError, OSError)):
            self.do_import()
        self.assertFalse(self.directory.exists())

    def test_ids_are_literal_lowercase_32hex(self):
        for bad in ('a' * 31, 'a' * 33, 'A' * 32, '../' + 'a' * 32, '/', '', ' a' * 16, True, 12):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.do_import(take_id=bad)
            with self.subTest(read_bad=bad), self.assertRaises(ValueError):
                ct.get_take(self.work, bad)
        self.assertFalse(self.work.exists())

    def test_source_outside_root_or_traversal_refused(self):
        for root, path in ((self.work, self.video),
                           (self.root, self.root / '..' / 'sources' / self.video.name)):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                ct.import_family(path, self.mctx, self.cond, root=root, work=self.work,
                                 take_id=self.take_id, captured_graph=self.graph)
        self.assertFalse(self.work.exists())

    def test_source_symlink_and_symlink_ancestor_refused(self):
        link = self.root / 'link.mp4'
        link.symlink_to(self.video)
        with self.assertRaises((ValueError, OSError)):
            ct.import_family(link, self.mctx, self.cond, root=self.root,
                             work=self.work, take_id=self.take_id, captured_graph=self.graph)
        linked_root = Path(self.tmp.name) / 'linked'
        linked_root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.do_import(root=linked_root)

    def test_fifo_refused_without_blocking(self):
        self.video.unlink()
        os.mkfifo(self.video)
        with self.assertRaises((ValueError, OSError)):
            self.do_import()
        self.assertFalse(self.directory.exists())

    def test_work_symlink_refused(self):
        elsewhere = Path(self.tmp.name) / 'elsewhere'
        elsewhere.mkdir()
        self.work.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.do_import()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_origin_strings_reject_path_url_secret_carriers(self):
        for field in ('source_job', 'operator_label'):
            for bad in ('../secret', '/home/operator', 'https://host/?token=x', 'x\\y', 'a\nb'):
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    self.do_import(**{field: bad})
        self.assertFalse(self.work.exists())

    def test_invalid_graph_and_completeness_refused(self):
        for graph in ([], 'not JSON', {}, {'bad': float('nan')}):
            with self.subTest(graph=graph), self.assertRaises(ValueError):
                self.do_import(captured_graph=graph)
        with self.assertRaises(ValueError):
            self.do_import(graph_completeness='guessed')
        with self.assertRaises(ValueError):
            self.do_import(captured_graph=None, graph_completeness='complete')

    def test_capsule_tamper_refused_even_on_metadata_read(self):
        self.do_import()
        value = json.loads((self.directory / 'capsule.json').read_bytes())
        value['lineage']['relation'] = 'fabricated'
        self.rewrite('capsule.json', json.dumps(value).encode())
        with self.assertRaises(ValueError):
            ct.get_take(self.work, self.take_id)
        with self.assertRaises(ValueError):
            ct.get_validated_family(self.work, self.take_id)

    def test_private_capture_tamper_refused_before_use(self):
        self.do_import()
        evidence = json.loads((self.directory / 'capture.private.json').read_bytes())
        evidence['captured_graph']['7']['inputs']['filename'] = 'changed'
        self.rewrite('capture.private.json', json.dumps(evidence).encode())
        with self.assertRaises(ValueError):
            ct.get_validated_family(self.work, self.take_id)

    def test_each_artifact_changed_is_refused_before_use(self):
        for index, name in enumerate(('take.mp4', 'take.mctx.safetensors', 'take.cond.safetensors')):
            self.take_id = str(index) * 32
            self.do_import()
            data = bytearray((self.directory / name).read_bytes())
            data[-1] ^= 1
            self.rewrite(name, data)
            with self.subTest(name=name), self.assertRaises(ValueError):
                ct.get_validated_family(self.work, self.take_id)

    def test_metadata_listing_does_not_claim_fresh_integrity_or_rehash(self):
        self.do_import()
        self.rewrite('take.mp4', b'changed')
        with patch('continuable_take.validate_h3_artifact_set', side_effect=AssertionError('rehash')):
            rows = ct.list_takes(self.work)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].to_manifest()['integrity'], 'frozen_metadata_only')
            self.assertEqual(ct.get_take(self.work, self.take_id), rows[0])

    def test_collision_does_not_replace_even_empty_destination(self):
        self.directory.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            self.do_import()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_racing_publication_no_clobber_and_staging_cleanup(self):
        publish = ct._publish_directory
        def racer(staging, destination):
            destination.mkdir()
            (destination / 'winner').write_text('keep')
            publish(staging, destination)
        with patch('continuable_take._publish_directory', side_effect=racer):
            with self.assertRaises(FileExistsError):
                self.do_import()
        self.assertEqual((self.directory / 'winner').read_text(), 'keep')
        self.assertEqual([p.name for p in self.directory.parent.iterdir()], [self.take_id])

    def test_changed_source_during_copy_refused_and_staging_cleaned(self):
        copy = ct._copy_file
        def changing(source, destination, expected):
            result = copy(source, destination, expected)
            if source == self.cond:
                self.video.write_bytes(b'changed after initial inspection')
            return result
        with patch('continuable_take._copy_file', side_effect=changing):
            with self.assertRaises(ValueError):
                self.do_import()
        self.assertFalse(self.directory.exists())
        self.assertEqual(list(self.directory.parent.iterdir()), [])

    def test_unknown_lineage_never_inferred_and_unsafe_values_private_only(self):
        del self.meta['parent_id']
        self.meta['relation'] = 'https://secret.invalid/?key=SECRET'
        self.write_mctx()
        value = self.do_import().to_manifest()
        self.assertIsNone(value['lineage']['parent_id'])
        self.assertIsNone(value['lineage']['relation'])
        self.assertNotIn('SECRET', json.dumps(value))

    def test_list_is_id_scoped_sorted_and_missing_store_read_has_no_side_effects(self):
        self.assertEqual(ct.list_takes(self.work), ())
        self.assertFalse(self.work.exists())
        self.do_import()
        self.take_id = '0' * 32
        self.do_import()
        (self.directory.parent / '.partial').mkdir()
        (self.directory.parent / 'unrelated').mkdir()
        rows = ct.list_takes(self.work)
        self.assertEqual([row.take_id for row in rows], ['0' * 32, 'a' * 32])

    def test_import_purity_without_site_packages_or_runtime_configuration(self):
        src = Path(__file__).resolve().parents[1] / 'src'
        code = """
import os, pathlib, sys
before = dict(os.environ)
sys.path.insert(0, sys.argv[1])
import continuable_take
assert before == dict(os.environ)
assert not any(x in sys.modules for x in ('torch', 'config', 'comfy_sdk', 'comfy_transport', 'app'))
assert list(pathlib.Path('.').iterdir()) == []
"""
        empty = Path(self.tmp.name) / 'empty'
        empty.mkdir()
        run = subprocess.run([sys.executable, '-B', '-S', '-c', code, str(src)],
                             cwd=empty, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_omitted_id_generates_strict_native_id(self):
        record = self.do_import(take_id=None)
        self.assertRegex(record.take_id, r'^[0-9a-f]{32}$')
        self.assertEqual(ct.get_take(self.work, record.take_id), record)

    def test_symlink_artifact_cannot_be_used_after_publication(self):
        self.do_import()
        self.directory.chmod(0o700)
        artifact = self.directory / 'take.mp4'
        artifact.unlink()
        artifact.symlink_to(self.video)
        with self.assertRaises((ValueError, OSError)):
            ct.get_validated_family(self.work, self.take_id)

    def test_even_resealed_capsule_cannot_echo_arbitrary_public_paths(self):
        self.do_import()
        value = json.loads((self.directory / 'capsule.json').read_bytes())
        value['lineage']['pins'][0]['source_path'] = '/private/leak.mp4'
        value['capsule_sha256'] = ct._digest({k: v for k, v in value.items() if k != 'capsule_sha256'})
        self.rewrite('capsule.json', json.dumps(value).encode())
        with self.assertRaises(ValueError):
            ct.get_take(self.work, self.take_id)

    def test_captured_graph_reader_rejects_duplicates_symlinks_and_fifo(self):
        path = self.root / 'capture.json'
        path.write_text('{"x":1,"x":2}')
        with self.assertRaises(ValueError):
            ct.read_captured_graph(path)
        path.unlink()
        path.symlink_to(self.mctx)
        with self.assertRaises((ValueError, OSError)):
            ct.read_captured_graph(path)
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises((ValueError, OSError)):
            ct.read_captured_graph(path)

    def test_nonfinite_execution_json_retained_losslessly_as_opaque_not_repaired(self):
        raw = '{"7":{"class_type":"SyntheticTest","inputs":{"end":Infinity,"x":NaN}}}'
        capture = self.root / 'nonfinite.json'
        capture.write_text(raw)
        self.assertEqual(ct.read_captured_graph(capture), raw)
        record = self.do_import(captured_graph=raw)
        recipe = record.to_manifest()['recipe']
        self.assertEqual(recipe['graph_encoding'], 'opaque_text')
        self.assertEqual(recipe['app_replay'], 'unreviewed')
        canonical = json.dumps(json.loads(raw), sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True, allow_nan=True)
        self.assertEqual(recipe['graph_sha256'], hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual(recipe['graph_canonicalization'], 'python-json-sort-keys-ascii-nonfinite-v1')
        evidence = json.loads((self.directory / 'capture.private.json').read_bytes())
        self.assertEqual(evidence['captured_graph'], raw)
        self.assertEqual(ct.get_validated_family(self.work, self.take_id).record, record)
        self.assertNotIn('Infinity', (self.directory / 'capsule.json').read_text())

    def make_real_cpu_fixture(self):
        """Real tiny MP4, still synthetic zero-tensor sidecars; never GPU evidence."""
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=black:s=32x32:r=24', '-frames:v', '5', '-an', '-c:v', 'libx264',
            '-threads', '1', '-pix_fmt', 'yuv420p', '-metadata',
            'prompt=' + json.dumps(self.graph), '-movflags', 'use_metadata_tags', str(self.video)],
            capture_output=True, check=True, timeout=30)
        old = self.meta['self_id']
        self.meta['self_id'] = hashlib.sha256(self.video.read_bytes()).hexdigest()
        self.write_mctx()
        self.cond.write_bytes(self.cond.read_bytes().replace(old.encode(), self.meta['self_id'].encode()))
        self.probe.stop()

    def test_actual_embedded_prompt_capture_and_mismatch_refusal(self):
        self.make_real_cpu_fixture()
        self.assertEqual(ct.read_embedded_prompt(self.video), self.graph)
        with self.assertRaises(ValueError):
            self.do_import(captured_graph={'invented': 'not the run'}, graph_source='mp4_prompt')
        self.assertFalse(self.work.exists())
        record = self.do_import(graph_source='mp4_prompt')
        self.assertEqual(record.to_manifest()['recipe']['source'], 'mp4_prompt')
        self.assertEqual(ct.get_validated_family(self.work, self.take_id).record, record)

    def cli_args(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'import_h3_take.py'
        return [sys.executable, '-B', str(script), '--video', str(self.video),
                '--mctx', str(self.mctx), '--cond', str(self.cond), '--root', str(self.root),
                '--work', str(self.work), '--take-id', self.take_id]

    def test_cli_real_cpu_fixture_and_readback(self):
        self.make_real_cpu_fixture()
        run = subprocess.run(self.cli_args() + ['--embedded-prompt', '--graph-completeness',
                             'complete', '--label', 'synthetic-cpu'],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        output = json.loads(run.stdout)
        self.assertTrue(output['validation']['freshly_validated'])
        self.assertEqual(output['validation']['runtime_compatibility'], 'unproven')
        self.assertNotIn('SECRET', run.stdout)
        self.assertEqual(ct.get_validated_family(self.work, self.take_id).record.take_id, self.take_id)

    def test_cli_requires_explicit_evidence_and_redacts_failures(self):
        run = subprocess.run(self.cli_args(), capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 2)
        self.assertFalse(self.work.exists())
        capture = self.root / 'capture.json'
        capture.write_text('{"token":"SECRET", invalid}')
        run = subprocess.run(self.cli_args() + ['--captured-graph', str(capture)],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 1)
        self.assertNotIn('SECRET', run.stderr)
        self.assertNotIn(str(self.root), run.stderr)
        self.assertFalse(self.work.exists())


if __name__ == '__main__':
    unittest.main()
