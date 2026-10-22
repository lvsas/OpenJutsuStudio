"""Hermetic envelope tests, not evidence of GPU continuity or SDK transport."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from safetensor_header import HeaderValidationError, read_safetensors_header
from timeline_artifacts import ArtifactValidationError, validate_h3_artifact_set


_DTYPES = {'U8': 1, 'F16': 2, 'F32': 4}


def tensor_file(tensors, metadata, *, override=None):
    """Encode small, explicit safetensors fixtures without torch/safetensors."""
    header = {'__metadata__': metadata}
    payload = bytearray()
    for name, (dtype, shape, data) in tensors.items():
        if data is None:
            elements = 1
            for dimension in shape:
                elements *= dimension
            data = bytes(elements * _DTYPES[dtype])
        start = len(payload)
        payload.extend(data)
        header[name] = {'dtype': dtype, 'shape': shape, 'data_offsets': [start, len(payload)]}
    if override:
        override(header)
    raw = json.dumps(header, separators=(',', ':')).encode()
    raw += b' ' * (-len(raw) % 8)
    return struct.pack('<Q', len(raw)) + raw + payload


def json_envelope(text, payload=b''):
    raw = text.encode()
    return struct.pack('<Q', len(raw)) + raw + payload


class HeaderTests(unittest.TestCase):
    def setUp(self):
        self.tensors = {'value': ('F16', [2, 3], None)}

    def test_reads_only_header_and_owns_immutable_metadata(self):
        class ObservedBytes(io.BytesIO):
            read_bytes = 0

            def read(self, size=-1):
                value = super().read(size)
                self.read_bytes += len(value)
                return value

        stream = ObservedBytes(tensor_file(self.tensors, {'format': 'fixture', 'extra': 'kept'}))
        header = read_safetensors_header(stream)
        self.assertEqual(stream.read_bytes, header.data_start)
        self.assertEqual(header.tensors['value'].shape, (2, 3))
        self.assertEqual(header.metadata['extra'], 'kept')
        with self.assertRaises(TypeError):
            header.metadata['format'] = 'changed'

    def test_header_bound_and_truncation(self):
        for data in (b'', b'1234', struct.pack('<Q', 0),
                     struct.pack('<Q', 9 * 1024 * 1024), struct.pack('<Q', 100) + b'{}'):
            with self.subTest(data=data[:10]), self.assertRaises(HeaderValidationError):
                read_safetensors_header(io.BytesIO(data))

    def test_rejects_duplicate_keys_and_non_json_numbers(self):
        for text in ('{"__metadata__":{},"x":{},"x":{}}',
                     '{"__metadata__":{"a":"x","a":"y"}}',
                     '{"__metadata__":{"bad":NaN}}', '[]', '{}'):
            with self.subTest(text=text), self.assertRaises(HeaderValidationError):
                read_safetensors_header(io.BytesIO(json_envelope(text)))

    def test_rejects_bad_tensor_index(self):
        cases = [
            lambda h: h['value'].update(dtype='PICKLE'),
            lambda h: h['value'].update(shape=[True, 3]),
            lambda h: h['value'].update(shape=[-1, 3]),
            lambda h: h['value'].update(data_offsets=[0, 999]),
            lambda h: h['value'].update(data_offsets=[1, 12]),
            lambda h: h['value'].update(data_offsets=[0, True]),
            lambda h: h['value'].update(shape=[2, 4]),
            lambda h: h.update(__metadata__={'bad': 1}),
        ]
        for mutate in cases:
            with self.subTest(mutate=mutate), self.assertRaises(HeaderValidationError):
                read_safetensors_header(io.BytesIO(tensor_file(self.tensors, {}, override=mutate)))

    def test_rejects_overlap_holes_and_trailing_payload(self):
        tensors = {'a': ('U8', [2], None), 'b': ('U8', [2], None)}
        for offsets in ([1, 3], [3, 5]):
            data = tensor_file(tensors, {}, override=lambda h: h['b'].update(data_offsets=offsets))
            with self.subTest(offsets=offsets), self.assertRaises(HeaderValidationError):
                read_safetensors_header(io.BytesIO(data))
        with self.assertRaises(HeaderValidationError):
            read_safetensors_header(io.BytesIO(tensor_file(tensors, {}) + b'x'))

    def test_accepts_scalar_and_zero_sized_tensor(self):
        tensors = {'empty': ('F16', [0], None), 'scalar': ('F32', [], None)}
        self.assertEqual(set(read_safetensors_header(io.BytesIO(tensor_file(tensors, {}))).tensors),
                         {'empty', 'scalar'})


class ArtifactSetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = self.root / 'take.mp4'
        self.mctx = self.root / 'take.mctx.safetensors'
        self.cond = self.root / 'take.cond.safetensors'
        self.probe_patch = patch('timeline_artifacts.probe_mp4', return_value={
            'width': 32, 'height': 32, 'fps': 24.0, 'frames': 5, 'duration': 5 / 24,
        })
        self.probe = self.probe_patch.start()
        self.addCleanup(self.probe_patch.stop)
        self.family()

    def family(self, *, context=None, cond_meta=None, structure=None, tensors=None):
        if not self.video.exists():
            self.video.write_bytes(b'explicit MP4 byte fixture; ffprobe is mocked')
        identity = hashlib.sha256(self.video.read_bytes()).hexdigest()
        meta = {'format': 'mctx_v1', 'self_id': identity, 'width': '32', 'height': '32',
                'fps': '24', 'raw_frames': '5', 'delivered_frames': '5'}
        meta.update(context or {})
        self.mctx.write_bytes(tensor_file(tensors or {
            'video': ('F16', [1, 24, 2, 2, 2], None),
            'audio': ('F16', [1, 32, 2, 5], None),
        }, meta))
        if structure is None:
            structure = {'__list__': [{'__list__': [
                {'__tensor__': 'cond/0/0'}, {'__dict__': {'tag': 'fixture'}}]}]}
        encoded = json.dumps(structure).encode()
        cm = {'format': 'obvpm_cond_v1', 'self_id': identity}
        cm.update(cond_meta or {})
        self.cond.write_bytes(tensor_file({
            'cond/0/0': ('F32', [1, 2, 3], None),
            'structure': ('U8', [len(encoded)], encoded),
        }, cm))

    def validate(self, **kwargs):
        return validate_h3_artifact_set(self.video, self.mctx, self.cond, root=self.root, **kwargs)

    def test_exact_comfyui_dedup_paths_keep_bytes_and_manifest(self):
        baseline = self.validate()
        for count in (1, 23):
            names = (f'take ({count}).mp4', f'take.mctx ({count}).safetensors',
                     f'take.cond ({count}).safetensors')
            paths = []
            for source, name in zip((self.video, self.mctx, self.cond), names):
                path = self.root / name
                path.write_bytes(source.read_bytes())
                paths.append(path)
            self.assertEqual(validate_h3_artifact_set(*paths, root=self.root), baseline)

    def test_suffix_policy_is_role_specific_and_only_allows_numeric_final_extension_counters(self):
        from timeline_artifacts import has_h3_role_suffix
        for name in ('take.mctx (1).safetensors', 'take.mctx (23).safetensors',
                     'take (1).mctx.safetensors', 'take.mctx.safetensors'):
            with self.subTest(name=name):
                self.assertTrue(has_h3_role_suffix(name, 'mctx'))
        for name in ('take.cond (1).safetensors', 'take.mctx (x).safetensors',
                     'take.mctx (-1).safetensors', 'take.mctx (1).safetensors.exe',
                     'take.mctx.safetensors (1)', 'take.mctx (1).safetensors/missing'):
            with self.subTest(name=name):
                self.assertFalse(has_h3_role_suffix(name, 'mctx'))

    def assert_invalid(self, code, call=None):
        with self.assertRaises(ArtifactValidationError) as raised:
            (call or self.validate)()
        self.assertEqual(raised.exception.code, code)
        self.assertNotIn(str(self.root), str(raised.exception))
        return raised.exception

    def test_valid_family_returns_path_free_manifest_without_exact_replay_claim(self):
        manifest = self.validate().to_manifest()
        self.assertEqual(manifest['schema_version'], 1)
        self.assertEqual(set(manifest['assets']), {'video', 'mctx', 'conditioning'})
        self.assertEqual(manifest['context']['delivered_frames'], 5)
        self.assertFalse(manifest['verification']['model_runtime_compatibility'])
        self.assertFalse(manifest['verification']['conditioning_tensor_values'])
        text = json.dumps(manifest)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn('exact_refinable', text)
        self.probe.assert_called_once_with(self.video.resolve())

    def test_missing_sidecars_and_empty_video_fail_without_removing_files(self):
        for target in (self.mctx, self.cond):
            self.family()
            target.unlink()
            self.assert_invalid('missing_artifact')
            self.assertTrue(self.video.exists())
        self.family()
        self.video.write_bytes(b'')
        self.assert_invalid('empty_artifact')

    def test_rejects_escaping_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / 'take.mp4'
            outside.write_bytes(b'x')
            self.assert_invalid('unsafe_path', lambda: validate_h3_artifact_set(
                outside, self.mctx, self.cond, root=self.root))
            self.video.unlink()
            self.video.symlink_to(outside)
            self.assert_invalid('unsafe_path')

    def test_rejects_non_regular_files_and_wrong_role_suffix(self):
        self.mctx.unlink()
        self.mctx.mkdir()
        self.assert_invalid('missing_artifact')
        wrong = self.root / 'take.safetensors'
        wrong.write_bytes(b'x')
        self.assert_invalid('unsupported_suffix', lambda: validate_h3_artifact_set(
            self.video, wrong, self.cond, root=self.root))

    def test_rejects_context_video_identity_mismatch(self):
        self.family(context={'self_id': '0' * 64})
        self.assert_invalid('identity_mismatch')

    def test_rejects_conditioning_context_identity_mismatch(self):
        self.family(cond_meta={'self_id': '0' * 64})
        self.assert_invalid('identity_mismatch')

    def test_rejects_wrong_format_and_malformed_identity(self):
        for context, conditioning in (({'format': 'future'}, {}), ({}, {'format': 'future'}),
                                       ({'self_id': 'not-a-hash'}, {})):
            self.family(context=context, cond_meta=conditioning)
            self.assert_invalid('unsupported_format' if 'format' in context or 'format' in conditioning
                                else 'invalid_metadata')

    def test_validates_index_even_with_valid_metadata(self):
        self.mctx.write_bytes(self.mctx.read_bytes()[:-1])
        self.assert_invalid('invalid_safetensors')

    def test_checks_declared_dimensions_frames_and_numeric_types(self):
        for change in ({'width': '0'}, {'height': '-1'}, {'fps': 'nan'},
                       {'delivered_frames': '6'}, {'raw_frames': '0'}, {'width': '32.0'}):
            self.family(context=change)
            self.assert_invalid('invalid_metadata')

    def test_checks_video_and_audio_tensor_geometry(self):
        for tensors in ({'video': ('F16', [1, 24, 2, 1, 2], None),
                         'audio': ('F16', [1, 32, 2, 5], None)},
                        {'video': ('F16', [1, 24, 2, 2, 2], None)},
                        {'video': ('F16', [2, 24, 2, 2, 2], None),
                         'audio': ('F16', [1, 32, 2, 5], None)},
                        {'video': ('U8', [1, 24, 2, 2, 2], None),
                         'audio': ('F16', [1, 32, 2, 5], None)}):
            self.family(tensors=tensors)
            self.assert_invalid('invalid_latents')

    def test_checks_decoded_media_against_delivered_not_raw_frames(self):
        self.family(context={'raw_frames': '22'})
        self.validate()
        for change in ({'width': 64}, {'height': 64}, {'frames': 22}, {'fps': 30.0}):
            self.probe.return_value = {'width': 32, 'height': 32, 'frames': 5, 'fps': 24.0, **change}
            self.assert_invalid('media_mismatch')

    @unittest.skipUnless(os.name == 'posix', 'CPU/memory limits require POSIX')
    def test_exponent_fps_is_refused_with_a_bounded_cpu_budget(self):
        self.family(context={'fps': '1e999999999'})
        source = Path(__file__).resolve().parents[1] / 'src'
        code = (
            'import sys, resource; '
            'resource.setrlimit(resource.RLIMIT_CPU, (1, 1)); '
            'resource.setrlimit(resource.RLIMIT_AS, (128*1024*1024, 128*1024*1024)); '
            f'sys.path.insert(0, {str(source)!r}); '
            'from timeline_artifacts import validate_h3_artifact_set, ArtifactValidationError; '
            f'root={str(self.root)!r}\n'
            'try:\n'
            ' validate_h3_artifact_set("take.mp4", "take.mctx.safetensors", '
            '"take.cond.safetensors", root=root)\n'
            'except ArtifactValidationError as exc:\n'
            ' print(exc.code, exc.role)\n')
        result = subprocess.run([sys.executable, '-c', code],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'invalid_metadata mctx')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools required')
    def test_renamed_hls_playlist_cannot_read_a_segment_outside_the_root(self):
        self.probe_patch.stop()
        with tempfile.TemporaryDirectory() as other:
            segment = Path(other) / 'outside.ts'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=c=blue:s=32x32:r=24', '-frames:v', '5', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', '-f', 'mpegts', str(segment)],
                           capture_output=True, check=True, timeout=20)
            self.video.write_text('#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXT-X-VERSION:3\n'
                                  '#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:0.208333,\n'
                                  f'{segment}\n#EXT-X-ENDLIST\n')
            self.family()
            error = self.assert_invalid('invalid_media')
            self.assertEqual(error.role, 'video')

    def test_invalid_media_fails_with_no_internal_path(self):
        self.probe.side_effect = ValueError(str(self.root))
        self.assert_invalid('invalid_media')

    def test_conditioning_structure_must_reference_existing_embeddings(self):
        for tree in ({'__list__': []}, {'__tensor__': 'cond/0/0'},
                     {'__list__': [{'__list__': [{'__tensor__': 'missing'}, {'__dict__': {}}]}]},
                     {'__list__': [{'__list__': [{'__tensor__': 'structure'}, {'__dict__': {}}]}]},
                     {'__list__': [{'__list__': [{'__tensor__': 'cond/0/0'}, {'bad_tag': 1}]}]}):
            self.family(structure=tree)
            self.assert_invalid('invalid_conditioning')

    def test_expected_hashes_detect_corruption_beyond_header(self):
        original = self.validate().to_manifest()
        expected = {role: asset['sha256'] for role, asset in original['assets'].items()}
        data = bytearray(self.mctx.read_bytes())
        data[-1] ^= 1
        self.mctx.write_bytes(data)
        self.assert_invalid('digest_mismatch', lambda: self.validate(expected_sha256=expected))

    def test_expected_hashes_must_cover_exactly_the_family(self):
        for expected in ({}, {'video': '0' * 64},
                         {'video': '0' * 64, 'mctx': 'bad', 'conditioning': '0' * 64}):
            self.assert_invalid('invalid_expected_hashes', lambda: self.validate(expected_sha256=expected))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools required')
    def test_real_decoded_mp4_and_structural_sidecars_without_gpu(self):
        self.probe_patch.stop()
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=blue:s=32x32:r=24', '-frames:v', '5', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', str(self.video)], check=True, capture_output=True,
                       timeout=20)
        self.family()
        self.assertEqual(self.validate().to_manifest()['context']['delivered_frames'], 5)
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts' /
                                      'inspect_h3_artifacts.py'), '--root', str(self.root),
                   '--video', 'take.mp4', '--mctx', 'take.mctx.safetensors',
                   '--conditioning', 'take.cond.safetensors']
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
        self.assertEqual(json.loads(result.stdout)['context']['delivered_frames'], 5)

    def test_import_and_cli_help_are_read_only_and_configuration_free(self):
        project = Path(__file__).resolve().parents[1]
        untouched = self.root / 'must-not-be-created'
        env = {**os.environ, 'OPENGENJUTSU_WORK': str(untouched), 'COMFY_BASE_URL': 'sentinel'}
        code = ('import sys, os, json; from pathlib import Path; from unittest.mock import patch; '
                f'sys.path.insert(0, {str(project / "src")!r})\n'
                'with patch.object(Path, "mkdir", side_effect=AssertionError("Unexpected mkdir")) as mkdir:\n'
                ' import timeline_artifacts\n'
                ' print(json.dumps({"config": "config" in sys.modules, '
                '"torch": "torch" in sys.modules, "sdk": "comfy_sdk" in sys.modules, '
                '"target": os.environ.get("COMFY_BASE_URL"), "mkdir_calls": mkdir.call_count}))')
        result = subprocess.run([sys.executable, '-c', code], env=env,
                                capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(json.loads(result.stdout),
                         {'config': False, 'torch': False, 'sdk': False,
                          'target': 'sentinel', 'mkdir_calls': 0})
        self.assertFalse(untouched.exists())
        subprocess.run([sys.executable, str(project / 'scripts' / 'inspect_h3_artifacts.py'), '--help'],
                       env=env, capture_output=True, check=True, timeout=20)
        self.assertFalse(untouched.exists())

    @unittest.skipUnless(os.name == 'posix', 'Named pipes require POSIX')
    def test_fifo_is_refused_without_waiting_for_a_writer(self):
        self.mctx.unlink()
        os.mkfifo(self.mctx)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts' /
                                 'inspect_h3_artifacts.py'), '--root', str(self.root),
             '--video', 'take.mp4', '--mctx', 'take.mctx.safetensors',
             '--conditioning', 'take.cond.safetensors'],
            capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 1)
        error = json.loads(result.stderr)['error']
        self.assertEqual((error['code'], error['role']), ('missing_artifact', 'mctx'))

    def test_mutation_during_media_probe_is_refused_with_exact_role(self):
        def mutate(_path):
            data = bytearray(self.cond.read_bytes())
            data[-1] ^= 1
            self.cond.write_bytes(data)
            return {'width': 32, 'height': 32, 'frames': 5, 'fps': 24.0}
        self.probe.side_effect = mutate
        # Simulate a coarse filesystem clock even on high-resolution hosts.
        with patch('timeline_artifacts._fingerprint', return_value=(0, 0, 0, 0, 0)):
            error = self.assert_invalid('artifact_changed')
        self.assertEqual(error.role, 'conditioning')

    def test_header_mutation_before_first_hash_is_refused(self):
        for role, target in (('mctx', self.mctx), ('conditioning', self.cond)):
            with self.subTest(role=role):
                self.family()
                mutated = []

                def read_then_mutate(stream):
                    header = read_safetensors_header(stream)
                    expected_format = 'mctx_v1' if role == 'mctx' else 'obvpm_cond_v1'
                    if header.metadata.get('format') == expected_format and not mutated:
                        original = target.read_bytes()
                        changed = original.replace(header.metadata['self_id'].encode(), b'0' * 64, 1)
                        self.assertNotEqual(original, changed)
                        self.assertEqual(len(original), len(changed))
                        target.write_bytes(changed)
                        mutated.append(True)
                    return header

                with patch('timeline_artifacts.read_safetensors_header',
                           side_effect=read_then_mutate), patch(
                               'timeline_artifacts._fingerprint', return_value=(0, 0, 0, 0, 0)):
                    error = self.assert_invalid('artifact_changed')
                self.assertEqual(error.role, role)
                self.assertEqual(mutated, [True])
                with target.open('rb') as stream:
                    self.assertEqual(read_safetensors_header(stream).metadata['self_id'], '0' * 64)

    def test_conditioning_depth_and_node_budgets_are_enforced(self):
        deep = None
        for _ in range(70):
            deep = {'__list__': [deep]}
        for extra in (deep, {'__list__': [None] * 100_001}):
            tree = {'__list__': [{'__list__': [
                {'__tensor__': 'cond/0/0'}, {'__dict__': {'bounded': extra}}]}]}
            self.family(structure=tree)
            self.assert_invalid('invalid_conditioning')

    def test_bounded_decimal_and_rational_fps_are_supported(self):
        for fps in ('24', '24.0', '24000/1000'):
            self.family(context={'fps': fps})
            self.assertEqual(self.validate().context.fps, 24.0)
        for fps in ('1e3', '1e-999999999', '1/0', ' 24', '+24', '2_4'):
            self.family(context={'fps': fps})
            self.assert_invalid('invalid_metadata')

    def test_mp4_probe_explicitly_blocks_external_resources(self):
        from media_probe import probe_mp4
        payload = json.dumps({'streams': [{'width': 32, 'height': 32,
                                          'avg_frame_rate': '24/1', 'nb_read_frames': '5'}]})
        with patch('media_probe.subprocess.run', return_value=subprocess.CompletedProcess(
                [], 0, stdout=payload)) as run:
            self.assertEqual(probe_mp4(self.video)['frames'], 5)
        arguments = run.call_args.args[0]
        for option, value in (('-protocol_whitelist', 'file'), ('-f', 'mov'),
                              ('-enable_drefs', '0'), ('-use_absolute_path', '0')):
            self.assertEqual(arguments[arguments.index(option) + 1], value)

    def test_cli_reports_missing_family_without_path_leak(self):
        self.cond.unlink()
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts' /
                                 'inspect_h3_artifacts.py'), '--root', str(self.root),
             '--video', 'take.mp4', '--mctx', 'take.mctx.safetensors',
             '--conditioning', 'take.cond.safetensors'],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stderr)['error']['code'], 'missing_artifact')
        self.assertEqual(result.stdout, '')
        self.assertNotIn(str(self.root), result.stderr)
