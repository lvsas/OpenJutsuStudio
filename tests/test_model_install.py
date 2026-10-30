"""Isolated installer contracts; no production model downloads."""
import contextlib
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import download_models as cli


def tensor(meta=None, payload=b'\x01\x02'):
    header = json.dumps(meta or {'x': {'dtype': 'U8', 'shape': [2], 'data_offsets': [0, 2]}}).encode()
    return struct.pack('<Q', len(header)) + header + payload


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'models').mkdir()
        self.body = tensor()
        self.source = {'url': 'https://example.org/model.safetensors', 'revision': 'verified-test',
                       'size_bytes': len(self.body), 'sha256': hashlib.sha256(self.body).hexdigest()}

    def manifest(self):
        folders = {'UNETLoader': 'diffusion_models', 'CLIPLoader': 'text_encoders',
                   'VAELoader': 'vae', 'VAELoaderKJ': 'vae', 'LoraLoaderModelOnly': 'loras',
                   'MinimaxH3LatentUpscaler3D': 'latent_upscale_models'}
        return {'models': [dict(role_key=r['key'], file=r['default'], folder=folders[r['class_type']],
                                download=dict(self.source)) for r in cli.roles()], 'loras': []}

    def item(self):
        return cli.build_plan(self.manifest(), 'ltx')[0][0]

    def response(self, data=None, length=None):
        stream = io.BytesIO(self.body if data is None else data)
        stream.headers = {} if length is None else {'Content-Length': str(length)}
        return stream

    def install(self, item=None, opener=None):
        return cli.fetch(item or self.item(), self.root, opener=opener or (lambda *a, **k: self.response()))

    def test_shipped_manifest_covers_every_fixed_swap_role(self):
        manifest = json.loads((ROOT / 'dependencies.json').read_text())
        plan, unresolved = cli.build_plan(manifest)
        self.assertEqual(unresolved, [])
        swap = {role['key'] for role in cli.roles()}
        swap_items = [item for item in plan if item['role_key'] in swap]
        self.assertEqual({item['role_key'] for item in swap_items}, swap)
        for item in swap_items:
            source = item['download']
            self.assertRegex(source['revision'], r'^[0-9a-f]{40}$')
            self.assertIn('/resolve/' + source['revision'] + '/', source['url'])
            self.assertGreater(source['size_bytes'], 8)
            self.assertRegex(source['sha256'], r'^[0-9a-f]{64}$')
            self.assertEqual(source['integrity_source'], 'huggingface-lfs-metadata')
        # Character files live on a gated repository: pinned, sized, but with no
        # published hash. They must say so rather than pretend to be verified.
        for item in plan:
            if item['role_key'] in swap:
                continue
            source = item['download']
            self.assertTrue(source.get('gated'), item['role_key'])
            self.assertNotIn('sha256', source, item['role_key'])
            self.assertEqual(source['integrity_source'], 'huggingface-gated-no-published-hash')

    def test_signed_huggingface_redirect_allowed_without_logging_url(self):
        from model_download import SafeRedirect
        request = urllib.request.Request(self.source['url'])
        url = 'https://cas-bridge.xethub.hf.co/model?Signature=fixture'
        redirected = SafeRedirect().redirect_request(request, None, 302, 'found', {}, url)
        self.assertEqual(redirected.full_url, url)

    def test_gated_access_warning_is_plan_only(self):
        manifest = self.manifest()
        manifest['models'][0]['download']['access'] = 'gated'
        path = self.root / 'manifest.json'
        path.write_text(json.dumps(manifest))
        output = io.StringIO()
        with mock.patch.object(cli, 'fetch', side_effect=AssertionError('network')), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['--comfyui', str(self.root), '--manifest', str(path)]), 0)
        self.assertIn('ACCESS GATED', output.getvalue())

    def test_root_symlink_and_incomplete_http_response_are_safe(self):
        import http.client
        linked = self.root / 'linked-root'
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            cli.fetch(self.item(), linked, opener=mock.Mock(side_effect=AssertionError('network')))
        with self.assertRaisesRegex(ValueError, '^Installation failed'):
            self.install(opener=mock.Mock(side_effect=http.client.IncompleteRead(b'partial', 10)))
        self.assertFalse((self.root / 'models' / self.item()['relative']).exists())

    def test_malformed_headers_and_duplicate_tensor_names_are_rejected(self):
        from model_download import validate_file
        headers = [b'[]', b'{"x":1}',
                   b'{"x":{"dtype":"U8","shape":[2],"data_offsets":[0,2]},"x":{"dtype":"U8","shape":[2],"data_offsets":[0,2]}}']
        for header in headers:
            with self.assertRaises(ValueError):
                validate_file(io.BytesIO(struct.pack('<Q', len(header)) + header + b'xx'), {})

    def test_engine_plans_and_missing_duplicate_sources(self):
        manifest = self.manifest()
        self.assertEqual([len(cli.build_plan(manifest, e)[0]) for e in ('ltx', 'h3', 'all')], [8, 7, 15])
        self.assertFalse(cli.build_plan(manifest)[1])
        del manifest['models'][0]['download']
        self.assertTrue(cli.build_plan(manifest)[1])
        manifest = self.manifest()
        manifest['loras'].append(manifest['models'][0])
        self.assertTrue(cli.build_plan(manifest)[1])

    def test_manifest_contract_and_url_rejection(self):
        for field, bad in [('file', '../x'), ('file', 'C:\\x'), ('file', 'x\ny'),
                           ('folder', 'vae'), ('role_key', 'unknown')]:
            with self.subTest(field=field, bad=bad):
                manifest = self.manifest()
                manifest['models'][0][field] = bad
                self.assertTrue(cli.build_plan(manifest)[1])
        for url in ['http://example.org/x', 'https://u:p@example.org/x',
                    'https://example.org/x?secret=abc', 'https://example.org/x#f', 'https://example.org/\nx']:
            manifest = self.manifest()
            manifest['models'][0]['download']['url'] = url
            self.assertTrue(cli.build_plan(manifest)[1])

    def test_default_and_dry_run_no_network_or_writes(self):
        path = self.root / 'manifest.json'
        path.write_text(json.dumps(self.manifest()))
        before = list(self.root.rglob('*'))
        with mock.patch.object(cli, 'fetch', side_effect=AssertionError('network')), contextlib.redirect_stdout(io.StringIO()):
            args = ['--comfyui', str(self.root), '--manifest', str(path)]
            self.assertEqual(cli.main(args), 0)
            self.assertEqual(cli.main(args + ['--download', '--dry-run']), 0)
            path.write_text(json.dumps({'models': [], 'loras': []}))
            self.assertNotEqual(cli.main(args), 0)
        self.assertEqual(list(self.root.rglob('*')), before)

    def test_roundtrip_local_server_injected_opener_and_existing_skip(self):
        body = self.body
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            opener = lambda *a, **k: urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/', timeout=3)
            result = self.install(opener=opener)
            self.assertIn('installed', result)
            target = self.root / 'models' / self.item()['relative']
            self.assertEqual(target.read_bytes(), self.body)
            self.assertIn('skip', self.install(opener=mock.Mock(side_effect=AssertionError('network'))))
            self.assertEqual(len(list(target.parent.glob('*.part'))), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_truncation_html_hash_and_content_length_fail_retained(self):
        for data, length, alter in [(self.body[:-1], len(self.body), False), (b'<html>denied</html>', None, False),
                                    (b'{"error":"denied"}', None, False), (self.body, len(self.body) + 1, False),
                                    (self.body + b'x', None, False), (self.body, None, True)]:
            with self.subTest(data=data, length=length, alter=alter):
                item = self.item()
                if alter:
                    item['download']['sha256'] = '0' * 64
                with self.assertRaises(ValueError):
                    self.install(item, lambda *a, **k: self.response(data, length))
                self.assertFalse((self.root / 'models' / item['relative']).exists())
        self.assertEqual(len(list((self.root / 'models').rglob('*.part'))), 6)

    def test_existing_corrupt_and_part_preserved(self):
        target = self.root / 'models' / self.item()['relative']
        target.parent.mkdir()
        target.write_bytes(b'bad')
        partial = target.with_suffix('.part')
        partial.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            self.install(opener=mock.Mock(side_effect=AssertionError('network')))
        self.assertEqual(target.read_bytes(), b'bad')
        self.assertEqual(partial.read_bytes(), b'keep')

    def test_symlink_components_and_existing_target_refused(self):
        item = self.item()
        outside = self.root / 'outside'
        outside.mkdir()
        folder = self.root / 'models' / Path(item['relative']).parent
        folder.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.install()
        self.assertFalse(list(outside.iterdir()))
        # A separate isolated root tests the existing-target link.
        other = self.root / 'other'
        (other / 'models' / Path(item['relative']).parent).mkdir(parents=True)
        target = other / 'models' / item['relative']
        target.symlink_to(self.root / 'missing')
        with self.assertRaises(ValueError):
            cli.fetch(item, other, opener=lambda *a, **k: self.response())
        self.assertTrue(target.is_symlink())

    def test_concurrent_target_no_clobber(self):
        item = self.item()
        target = self.root / 'models' / item['relative']
        def opener(*a, **k):
            target.write_bytes(b'concurrent')
            return self.response()
        with self.assertRaises(ValueError):
            self.install(item, opener)
        self.assertEqual(target.read_bytes(), b'concurrent')
        self.assertEqual(len(list(target.parent.glob('*.part'))), 1)

    def test_safetensors_shape_offsets_and_header_bounds(self):
        from model_download import validate_file
        for body in [tensor({'x': {'dtype': 'U8', 'shape': [3], 'data_offsets': [0, 2]}}),
                     tensor({'x': {'dtype': 'U8', 'shape': [2], 'data_offsets': [1, 3]}}),
                     struct.pack('<Q', 32 * 1024 * 1024 + 1), tensor({'x': {'dtype': 'bad', 'shape': [2], 'data_offsets': [0, 2]}})]:
            with self.assertRaises(ValueError):
                validate_file(io.BytesIO(body), {})

    def test_redirect_validation_and_generic_network_failure(self):
        from model_download import SafeRedirect
        redirect = SafeRedirect()
        request = urllib.request.Request(self.source['url'])
        for url in ['http://example.org/x', 'https://u:p@example.org/x', 'https://example.org/x?token=secret']:
            with self.assertRaises(ValueError):
                redirect.redirect_request(request, None, 302, 'found', {}, url)
        with self.assertRaisesRegex(ValueError, '^Installation failed') as caught:
            self.install(opener=mock.Mock(side_effect=OSError('https://user:SECRET@example.org')))
        self.assertNotIn('SECRET', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
