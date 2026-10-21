"""CPU adapter tests. Structural sidecars are unit fixtures, NOT native H3 proof."""
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def tensor_file(tensors, metadata):
    header, payload = {'__metadata__': metadata}, bytearray()
    sizes = {'F16': 2, 'F32': 4, 'U8': 1}
    for name, (dtype, shape, data) in tensors.items():
        data = data if data is not None else bytes(math.prod(shape) * sizes[dtype])
        start = len(payload)
        payload.extend(data)
        header[name] = {'dtype': dtype, 'shape': shape, 'data_offsets': [start, len(payload)]}
    raw = json.dumps(header).encode()
    return struct.pack('<Q', len(raw)) + raw + payload


class ContinuityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nodes = importlib.import_module('custom_nodes.opengenjutsu_continuity.nodes')
        cls.io = importlib.import_module('custom_nodes.opengenjutsu_continuity.family')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / 'input'
        self.output = self.root / 'output'
        self.input.mkdir()
        self.output.mkdir()
        self.folders = patch.dict(sys.modules, {'folder_paths': SimpleNamespace(
            get_input_directory=lambda: str(self.input), get_output_directory=lambda: str(self.output))})
        self.folders.start()
        self.addCleanup(self.folders.stop)
        video = self.input / 'uploads/a/dedup.mp4'
        video.parent.mkdir(parents=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=32x32:r=24',
                        '-frames:v', '5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
        identity = hashlib.sha256(video.read_bytes()).hexdigest()
        meta = {'format': 'mctx_v1', 'self_id': identity, 'width': '32', 'height': '32',
                'fps': '24', 'raw_frames': '5', 'delivered_frames': '5'}
        structure = json.dumps({'__list__': [{'__list__': [
            {'__tensor__': 'embedding'}, {'__dict__': {}}]}]}).encode()
        mctx = self.input / 'uploads/b/other.mctx.safetensors'
        cond = self.input / 'entirely/different/renamed.cond.safetensors'
        mctx.parent.mkdir(parents=True)
        cond.parent.mkdir(parents=True)
        mctx.write_bytes(tensor_file({'video': ('F16', [1, 24, 2, 2, 2], None),
                                      'audio': ('F16', [1, 32, 2, 5], None)}, meta))
        cond.write_bytes(tensor_file({'embedding': ('F32', [1, 2, 3], None),
                                      'structure': ('U8', [len(structure)], structure)},
                                     {'format': 'obvpm_cond_v1', 'self_id': identity}))
        self.paths = [video, mctx, cond]
        self.args = dict(zip(('video', 'mctx', 'conditioning'),
                             (p.relative_to(self.input).as_posix() for p in self.paths)))

    def restage(self, **overrides):
        return self.nodes.OpenGenjutsuH3RestageFamily().execute(**(self.args | {'family_name': 'proof'} | overrides))

    def test_restage_fixed_names_hashes_and_output_relative_handle(self):
        result = self.restage()
        handle, manifest = result['result']
        self.assertEqual(handle, 'opengenjutsu_continuity/proof/take.mp4')
        folder = self.output / 'opengenjutsu_continuity/proof'
        names = ['take.mp4', 'take.mctx.safetensors', 'take.cond.safetensors']
        self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(names))
        for source, name in zip(self.paths, names):
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                             hashlib.sha256((folder / name).read_bytes()).hexdigest())
        self.assertEqual(result['ui']['files'], [
            {'filename': name, 'subfolder': 'opengenjutsu_continuity/proof', 'type': 'output'} for name in names])
        self.assertNotIn(str(self.root), manifest)
        self.assertFalse(json.loads(manifest)['verification']['model_runtime_compatibility'])

    def test_publisher_literal_descriptors_explicit_paths(self):
        result = self.restage()
        folder = self.output / 'opengenjutsu_continuity/proof'
        pub = self.nodes.OpenGenjutsuH3PublishFamily().execute(
            video=str(folder / 'take.mp4'), mctx='opengenjutsu_continuity/proof/take.mctx.safetensors',
            conditioning='opengenjutsu_continuity/proof/take.cond.safetensors')
        self.assertEqual(pub, result)

    def test_no_clobber_existing_empty_directory(self):
        destination = self.output / 'opengenjutsu_continuity/proof'
        destination.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'collision'):
            self.restage()
        self.assertEqual(list(destination.iterdir()), [])
        self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_repeat_does_not_overwrite(self):
        first = self.restage()
        with self.assertRaisesRegex(ValueError, 'collision'):
            self.restage()
        self.assertTrue((self.output / first['result'][0]).is_file())

    def test_names_traversal_absolute_and_symlink_escape(self):
        for name in ('../escape', '/absolute', '.', '..', 'x/y', 'x\\y', '', '.hidden', 'x\n'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.restage(family_name=name)
        for value in ('../missing.mp4', str(self.paths[0]), 'uploads/./a/dedup.mp4', 'x\\y.mp4'):
            with self.subTest(path=value), self.assertRaises(ValueError):
                self.restage(video=value)
        (self.input / 'escape.mp4').symlink_to(self.paths[0])
        with self.assertRaises(ValueError):
            self.restage(video='escape.mp4')
        (self.input / 'link').symlink_to(self.paths[0].parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.restage(video='link/dedup.mp4')

    def test_pack_directory_symlink_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.output / 'opengenjutsu_continuity').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.restage()
        self.assertEqual(list(outside.iterdir()), [])

    def test_nonregular_missing_wrong_suffix_and_identity(self):
        for args in ({'mctx': 'missing.mctx.safetensors'}, {'mctx': self.args['conditioning']},
                     {'video': 'uploads/a'}, {'conditioning': self.args['conditioning'] + '/bad'}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.restage(**args)
        cond = self.paths[2]
        cond.write_bytes(cond.read_bytes().replace(b'obvpm_cond_v1', b'obvpm_cond_v2'))
        with self.assertRaisesRegex(ValueError, 'unsupported_format'):
            self.restage()
        cond.write_bytes(cond.read_bytes().replace(b'obvpm_cond_v2', b'obvpm_cond_v1'))
        cond.write_bytes(cond.read_bytes().replace(hashlib.sha256(self.paths[0].read_bytes()).hexdigest().encode(), b'0' * 64))
        with self.assertRaisesRegex(ValueError, 'identity_mismatch'):
            self.restage()

    def test_partial_copy_failure_cleanup_and_path_free_error(self):
        with patch.object(self.io, '_copy_file', side_effect=OSError(str(self.root / 'secret'))):
            with self.assertRaises(ValueError) as error:
                self.restage()
        self.assertNotIn(str(self.root), str(error.exception))
        self.assertEqual(list((self.output / 'opengenjutsu_continuity').iterdir()), [])

    def test_source_mutation_during_copy_is_rejected(self):
        real = self.io._copy_file
        changed = False
        def mutate(*args, **kwargs):
            nonlocal changed
            result = real(*args, **kwargs)
            if not changed:
                changed = True
                with self.paths[0].open('ab') as stream:
                    stream.write(b'changed')
            return result
        with patch.object(self.io, '_copy_file', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'artifact_changed'):
                self.restage()
        self.assertEqual(list((self.output / 'opengenjutsu_continuity').iterdir()), [])

    def test_unsupported_atomic_publish_fails_closed(self):
        with patch.object(self.io, '_rename_noreplace', side_effect=self.io.ContinuityError('unsupported_atomic_publish')):
            with self.assertRaisesRegex(ValueError, 'unsupported_atomic_publish'):
                self.restage()
        self.assertEqual(list((self.output / 'opengenjutsu_continuity').iterdir()), [])

    def test_publisher_different_stems_no_invented_loader_handle(self):
        for path in self.paths:
            destination = self.output / path.relative_to(self.input)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
        result = self.nodes.OpenGenjutsuH3PublishFamily().execute(**self.args)
        self.assertEqual(result['result'][0], '')
        self.assertEqual(len(result['ui']['files']), 3)
        for descriptor, path in zip(result['ui']['files'], self.paths):
            self.assertEqual(descriptor, {'filename': path.name,
                'subfolder': path.relative_to(self.input).parent.as_posix(), 'type': 'output'})

    def test_existing_final_file_and_symlink_are_never_overwritten(self):
        parent = self.output / 'opengenjutsu_continuity'
        parent.mkdir()
        final = parent / 'proof'
        final.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'collision'):
            self.restage()
        self.assertEqual(final.read_bytes(), b'keep')
        final.unlink()
        outside = self.root / 'outside'
        outside.mkdir()
        final.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'collision'):
            self.restage()
        self.assertTrue(final.is_symlink())
        self.assertEqual(list(outside.iterdir()), [])

    def test_fifo_is_refused_without_blocking(self):
        os.mkfifo(self.input / 'pipe.mp4')
        with self.assertRaisesRegex(ValueError, 'not_regular_file'):
            self.restage(video='pipe.mp4')

    def test_publisher_absolute_escape_symlink_and_pathfree_failure(self):
        for value in (str(self.paths[0]), '../input/uploads/a/dedup.mp4'):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                self.nodes.OpenGenjutsuH3PublishFamily().execute(video=value,
                    mctx=self.args['mctx'], conditioning=self.args['conditioning'])
            self.assertNotIn(str(self.root), str(error.exception))
        (self.output / 'linked.mp4').symlink_to(self.paths[0])
        with self.assertRaises(ValueError):
            self.nodes.OpenGenjutsuH3PublishFamily().execute(video='linked.mp4',
                mctx=self.args['mctx'], conditioning=self.args['conditioning'])

    def test_copy_corruption_fails_second_validation_and_cleans_stage(self):
        real = self.io._copy_file
        def corrupt(fd, directory, name):
            real(fd, directory, name)
            if name == 'take.cond.safetensors':
                target = os.open(name, os.O_WRONLY | os.O_APPEND, dir_fd=directory)
                try:
                    os.write(target, b'corruption')
                finally:
                    os.close(target)
        with patch.object(self.io, '_copy_file', side_effect=corrupt), self.assertRaises(ValueError):
            self.restage()
        self.assertEqual(list((self.output / 'opengenjutsu_continuity').iterdir()), [])

    def test_atomic_collision_created_during_publish(self):
        real = self.io._rename_noreplace
        def collide(parent, source, destination):
            os.mkdir(destination, dir_fd=parent)
            real(parent, source, destination)
        with patch.object(self.io, '_rename_noreplace', side_effect=collide):
            with self.assertRaisesRegex(ValueError, 'collision'):
                self.restage()
        final = self.output / 'opengenjutsu_continuity/proof'
        self.assertEqual(list(final.iterdir()), [])
        self.assertEqual(list(final.parent.iterdir()), [final])

    def test_installed_proxy_extractor_and_sdk_output_model(self):
        # Actual official implementation/model, but a synthetic history entry:
        # this is NOT a live Comfy job, transport or native loader roundtrip.
        from comfy_api_proxy.app import Proxy
        from comfy_low.models import Output as LowOutput
        from comfy_sdk.outputs import Output
        result = self.restage()
        proxy = Proxy('http://unit.invalid')
        outputs = proxy._outputs('unit-job', {'outputs': {'17': result['ui']}}, 'http://unit.invalid')
        wrapped = [Output(LowOutput.model_validate(item), None) for item in outputs]
        self.assertEqual([item.node_id for item in wrapped], ['17'] * 3)
        self.assertEqual([item.name for item in wrapped], ['take.mp4', 'take.mctx.safetensors', 'take.cond.safetensors'])
        self.assertEqual([item.type for item in wrapped], ['file'] * 3)
        self.assertEqual([proxy._decode_asset_id(item.id)['s'] for item in wrapped],
                         ['opengenjutsu_continuity/proof'] * 3)

    def test_proxy_asset_rewrite_uses_each_actual_input_location(self):
        from comfy_api_proxy.app import Proxy
        proxy = Proxy('http://unit.invalid')
        references = {}
        for role, path in zip(self.io.ROLES, self.paths):
            relative = path.relative_to(self.input)
            record = proxy.assets.add(hash_='unit-' + role, size_bytes=path.stat().st_size,
                content_type='application/octet-stream', file_path='ignored-requested-location/' + path.name,
                comfy_ref={'filename': path.name, 'subfolder': relative.parent.as_posix(), 'type': 'input'})
            references[role] = {'__type': 'core/ASSET', 'info': {'id': record.id}}
        missing = []
        actual = proxy._rewrite_asset_refs(references, missing)
        self.assertEqual(missing, [])
        self.assertEqual(actual, self.args)
        result = self.restage(**actual)
        self.assertEqual(result['result'][0], 'opengenjutsu_continuity/proof/take.mp4')

    def test_fake_mp4_and_geometry_mismatch_are_refused(self):
        original = self.paths[1].read_bytes()
        self.paths[1].write_bytes(original.replace(b'"delivered_frames": "5"', b'"delivered_frames": "4"'))
        with self.assertRaisesRegex(ValueError, 'media_mismatch'):
            self.restage()
        self.paths[1].write_bytes(original)
        old_hash = hashlib.sha256(self.paths[0].read_bytes()).hexdigest().encode()
        self.paths[0].write_bytes(b'not an MP4')
        new_hash = hashlib.sha256(self.paths[0].read_bytes()).hexdigest().encode()
        for path in self.paths[1:]:
            path.write_bytes(path.read_bytes().replace(old_hash, new_hash))
        with self.assertRaisesRegex(ValueError, 'invalid_media'):
            self.restage()

    def test_both_sidecars_required_even_if_video_has_neighbours(self):
        self.paths[2].unlink()
        with self.assertRaises(ValueError):
            self.restage()
        self.assertFalse((self.output / 'opengenjutsu_continuity/proof').exists())

    def test_schema_and_uncached_filesystem_nodes(self):
        for cls in (self.nodes.OpenGenjutsuH3PublishFamily, self.nodes.OpenGenjutsuH3RestageFamily):
            self.assertTrue(cls.OUTPUT_NODE)
            self.assertEqual(cls.RETURN_TYPES, ('STRING', 'STRING'))
            self.assertTrue(math.isnan(cls.IS_CHANGED()))
            for name in ('video', 'mctx', 'conditioning'):
                self.assertEqual(cls.INPUT_TYPES()['required'][name][0], 'STRING')


class PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = importlib.import_module('scripts.build_continuity_pack')

    def test_contracts_exact_generated_equality_and_import_whitelist(self):
        for relative, expected in self.builder.contract_payloads().items():
            self.assertEqual((self.builder.PACK / relative).read_bytes(), expected, relative)
        with self.assertRaises(ValueError):
            self.builder.private_contract('import torch\n')
        with self.assertRaises(ValueError):
            self.builder.private_contract('from unknown_contract import unsafe\n')

    def test_zip_byte_equality_determinism_and_allowlist(self):
        import io
        import re
        import zipfile
        first = self.builder.archive_bytes()
        second = self.builder.archive_bytes()
        self.assertEqual(first, second)
        self.assertEqual((REPO / 'dist/opengenjutsu-continuity.zip').read_bytes(), first)
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            expected = {'opengenjutsu_continuity/' + path for path in self.builder.payloads()}
            self.assertEqual(set(archive.namelist()), expected)
            self.assertEqual(len(archive.namelist()), len(expected))
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.external_attr >> 16, 0o100644)
                data = archive.read(info).decode('utf-8')
                self.assertNotIn('/home/', data)
                self.assertNotIn('192.168.', data)
                self.assertNotIn('BEGIN PRIVATE KEY', data)
                self.assertNotRegex(data, r'(?i)(?:api_key|password|secret)\s*=\s*[\"\'][^\"\']+[\"\']')
            license_text = archive.read('opengenjutsu_continuity/LICENSE').decode()
            self.assertIn('TERMS AND CONDITIONS', license_text)
            self.assertIn('END OF TERMS AND CONDITIONS', license_text)

    def test_zip_is_standalone_import_without_app_sdk_or_global_aliases(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            with zipfile.ZipFile(REPO / 'dist/opengenjutsu-continuity.zip') as archive:
                archive.extractall(directory)
            program = '''
import sys
before = list(sys.path)
import opengenjutsu_continuity as pack
assert sys.path == before
assert set(pack.NODE_CLASS_MAPPINGS) == {'OpenGenjutsuH3PublishFamily', 'OpenGenjutsuH3RestageFamily'}
for name in ('src', 'core', 'timeline_artifacts', 'safetensor_header', 'h3_conditioning', 'media_probe',
             'folder_paths', 'torch', 'safetensors', 'comfy_sdk', 'comfy_api_proxy'):
    assert name not in sys.modules, name
print('standalone import verified')
'''
            result = subprocess.run([sys.executable, '-S', '-c', program], cwd=directory,
                                    capture_output=True, text=True, check=True)
            self.assertIn('standalone import verified', result.stdout)


if __name__ == '__main__':
    unittest.main()
