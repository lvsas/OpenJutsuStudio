"""Unit-only SDK output fixtures; no GPU or live publication evidence."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from comfy_low.models import Output as OutputModel
from comfy_sdk.outputs import Output
from tests.test_timeline_artifact_contract import tensor_file
from h3_artifact_transport import download_h3_artifacts


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.destination = self.root / 'family'
        video = b'unit MP4 fixture, media probe mocked'
        identity = hashlib.sha256(video).hexdigest()
        meta = {'format': 'mctx_v1', 'self_id': identity, 'width': '32', 'height': '32',
                'fps': '24', 'raw_frames': '5', 'delivered_frames': '5'}
        structure = json.dumps({'__list__': [{'__list__': [
            {'__tensor__': 'embedding'}, {'__dict__': {}}]}]}).encode()
        self.data = {
            'video': video,
            'mctx': tensor_file({'video': ('F16', [1, 24, 2, 2, 2], None),
                                 'audio': ('F16', [1, 32, 2, 5], None)}, meta),
            'conditioning': tensor_file({'embedding': ('F32', [1, 2, 3], None),
                                         'structure': ('U8', [len(structure)], structure)},
                                        {'format': 'obvpm_cond_v1', 'self_id': identity}),
        }
        self.outputs = [self.output(role) for role in self.data]
        self.job = SimpleNamespace(id='unit-job', status='succeeded',
                                   get_outputs=lambda node: self.outputs)
        self.probe = patch('timeline_artifacts.probe_mp4', return_value={
            'width': 32, 'height': 32, 'fps': 24.0, 'frames': 5})
        self.probe.start()
        self.addCleanup(self.probe.stop)

    def output(self, role, **changes):
        suffix = {'video': '.mp4', 'mctx': '.mctx.safetensors',
                  'conditioning': '.cond.safetensors'}[role]
        fields = dict(id=f'unit-{role}', node_id='17', name=f'take{suffix}',
                      type='video' if role == 'video' else 'file',
                      content_type='application/octet-stream', size_bytes=len(self.data[role]),
                      hash=None, url='http://unit.invalid/content', url_expires_at='2030-01-01T00:00:00Z',
                      job_id='unit-job')
        fields.update(changes)
        output = Output(OutputModel.model_validate(fields), None)
        output.to_stream = lambda stream: stream.write(self.data[role])
        return output

    def download(self, **kwargs):
        return download_h3_artifacts(self.job, '17', self.destination, **kwargs)

    def assert_clean(self):
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_publishes_validated_family_and_manifest(self):
        result = self.download(expected_sha256={k: hashlib.sha256(v).hexdigest()
                                               for k, v in self.data.items()})
        self.assertEqual(result.context.self_id, hashlib.sha256(self.data['video']).hexdigest())
        self.assertEqual((self.destination / 'take.mp4').read_bytes(), self.data['video'])
        manifest = json.loads((self.destination / 'manifest.json').read_text())
        self.assertFalse(manifest['verification']['model_runtime_compatibility'])
        self.assertEqual(sorted(p.name for p in self.destination.iterdir()),
                         ['manifest.json', 'take.cond.safetensors', 'take.mctx.safetensors', 'take.mp4'])

    def test_missing_or_duplicate_or_unexpected_roles_refused_before_io(self):
        original = self.outputs[:]
        for outputs in ([], original[:1], original + [original[1]],
                        original + [self.output('video', name='extra.png')]):
            self.outputs = outputs
            with self.subTest(count=len(outputs)), self.assertRaises(ValueError):
                self.download()
            self.assert_clean()

    def test_opaque_string_path_or_dict_is_not_an_sdk_output(self):
        for value in ('/server/take.mp4', {'filename': 'take.mp4'}, SimpleNamespace(name='take.mp4')):
            self.outputs = [value]
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.download()
            self.assert_clean()

    def test_association_job_node_id_and_type_guards(self):
        for change in ({'job_id': 'other-job'}, {'job_id': None}, {'node_id': '18'},
                       {'type': 'image'}, {'id': ''}):
            self.outputs = [self.output('video', **change), self.output('mctx'),
                            self.output('conditioning')]
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.download()
            self.assert_clean()

    def test_untrusted_remote_names_cannot_escape_or_get_normalized(self):
        for name in ('../take.mp4', '/take.mp4', 'sub/take.mp4', 'sub\\take.mp4',
                     'take.MP4', 'take.mp4\x00'):
            self.outputs = [self.output('video', name=name), self.output('mctx'),
                            self.output('conditioning')]
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.download()
            self.assert_clean()

    def test_preflight_size_limit_and_invalid_limits(self):
        for limits in ({'video': 1, 'mctx': 10000, 'conditioning': 10000},
                       {}, {'video': True, 'mctx': 10000, 'conditioning': 10000}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.download(max_bytes=limits)
            self.assert_clean()

    def test_stream_limit_cannot_be_bypassed_by_zero_advertised_size(self):
        self.outputs[0] = self.output('video', size_bytes=0)
        with self.assertRaises(ValueError):
            self.download(max_bytes={'video': 1, 'mctx': 10000, 'conditioning': 10000})
        self.assert_clean()

    def test_download_failure_cleans_partial_family_without_fallback(self):
        def fail(stream):
            stream.write(b'partial')
            raise OSError('unit interrupted SDK stream')
        self.outputs[1].to_stream = fail
        with self.assertRaises(OSError):
            self.download()
        self.assert_clean()

    def test_lost_byte_association_is_an_error_and_cleans_family(self):
        self.data['video'] = b'different bytes'
        self.outputs[0] = self.output('video')
        with self.assertRaisesRegex(ValueError, 'identities differ'):
            self.download()
        self.assert_clean()

    def test_declared_size_mismatch_cleans_family(self):
        self.outputs[0] = self.output('video', size_bytes=999)
        with self.assertRaisesRegex(ValueError, 'size'):
            self.download()
        self.assert_clean()

    def test_existing_destination_is_not_replaced(self):
        self.destination.mkdir()
        sentinel = self.destination / 'sentinel'
        sentinel.write_text('keep')
        with self.assertRaises(FileExistsError):
            self.download()
        self.assertEqual(sentinel.read_text(), 'keep')
        self.assertEqual(list(self.root.iterdir()), [self.destination])

    def test_failed_job_is_not_downloaded(self):
        self.job.status = 'failed'
        with self.assertRaises(ValueError):
            self.download()
        self.assert_clean()

    def test_trusted_hash_mismatch_cleans_family(self):
        with self.assertRaisesRegex(ValueError, 'trusted hash'):
            self.download(expected_sha256={role: '0' * 64 for role in self.data})
        self.assert_clean()

    def test_symlink_destination_is_not_followed(self):
        self.destination.symlink_to(self.root / 'nonexistent-target')
        with self.assertRaises(FileExistsError):
            self.download()
        self.assertTrue(self.destination.is_symlink())
        self.assertFalse((self.root / 'nonexistent-target').exists())

    def test_unknown_size_download_remains_validated(self):
        self.outputs = [self.output(role, size_bytes=0) for role in self.data]
        self.assertEqual(self.download().context.width, 32)

    def test_invalid_node_and_missing_job_identity_refused(self):
        for node_id in ('../17', '', '17/18'):
            with self.subTest(node=node_id), self.assertRaises(ValueError):
                download_h3_artifacts(self.job, node_id, self.destination)
            self.assert_clean()
        self.job.id = ''
        with self.assertRaises(ValueError):
            self.download()
        self.assert_clean()

    def test_empty_download_cleans_family(self):
        self.data['video'] = b''
        self.outputs[0] = self.output('video', size_bytes=0)
        with self.assertRaisesRegex(ValueError, 'size'):
            self.download()
        self.assert_clean()

    def test_publication_failure_cleans_staging(self):
        with patch('h3_artifact_transport._publish_directory', side_effect=OSError('unit publish failure')):
            with self.assertRaises(OSError):
                self.download()
        self.assert_clean()


if __name__ == '__main__':
    unittest.main()
