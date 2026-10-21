"""CPU graph/SDK-handle contracts. Fake transport is unit-only, never a live-job proof."""
import copy
from contextlib import contextmanager
import importlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from h3_family_graphs import build_restage_graph, read_clip_handle, FAMILY_NODE, HANDLE_NODE

FAMILY = 'a' * 32


class FamilyGraphTests(unittest.TestCase):
    def references(self):
        return {role: {'__type': 'core/ASSET', 'info': {'id': f'unit-{role}',
                'file_path': 'unreliable-requested-name', 'hash': 'ignored-hint'}}
                for role in ('video', 'mctx', 'conditioning')}

    def test_actual_asset_tags_and_returned_handle_are_wired(self):
        refs = self.references(); before = copy.deepcopy(refs)
        graph = build_restage_graph(refs, FAMILY)
        self.assertEqual(refs, before)
        self.assertEqual(set(graph), {FAMILY_NODE, HANDLE_NODE})
        native = graph[FAMILY_NODE]
        self.assertEqual(native['class_type'], 'OpenGenjutsuH3RestageFamily')
        self.assertEqual(native['inputs']['family_name'], FAMILY)
        for role in refs:
            self.assertEqual(native['inputs'][role], {'__type': 'core/ASSET', 'info': {'id': f'unit-{role}'}})
        text = graph[HANDLE_NODE]
        self.assertEqual(text['class_type'], 'SaveText')
        self.assertEqual(text['inputs']['text'], [FAMILY_NODE, 0])
        self.assertEqual(text['inputs']['format'], 'txt')
        self.assertFalse(any(node['class_type'].startswith('Sampler') for node in graph.values()))
        self.assertFalse(any(node['class_type'] == 'H3LoadVideoWithMCtx' for node in graph.values()),
                         'The filename COMBO is bound only after reading the real returned handle')

    def test_installed_proxy_rewrites_ids_not_requested_upload_paths(self):
        from comfy_api_proxy.app import Proxy
        proxy = Proxy('http://unit.invalid'); refs = {}
        for role in ('video', 'mctx', 'conditioning'):
            asset = proxy.assets.add(hash_='unit-' + role, size_bytes=1,
                content_type='application/octet-stream', file_path='wrong/hint',
                comfy_ref={'filename': role + '.bin', 'subfolder': 'actual/' + role, 'type': 'input'})
            refs[role] = {'__type': 'core/ASSET', 'info': {'id': asset.id}}
        graph = build_restage_graph(refs, FAMILY); missing = []
        rewritten = proxy._rewrite_asset_refs(graph, missing)
        self.assertEqual(missing, [])
        for role in refs:
            self.assertEqual(rewritten[FAMILY_NODE]['inputs'][role], f'actual/{role}/{role}.bin')

    def test_missing_state_bad_ids_and_raw_paths_are_rejected(self):
        for invalid in ('../bad', 'A' * 32, '', True):
            with self.subTest(family=invalid), self.assertRaises(ValueError):
                build_restage_graph(self.references(), invalid)
        for patch in ({'conditioning': None}, {'mctx': 'input/inferred.mctx.safetensors'},
                      {'video': {'type': 'core/ASSET', 'info': {'id': 'wrong-tag'}}}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                build_restage_graph(self.references() | patch, FAMILY)
        refs = self.references(); refs.pop('conditioning')
        with self.assertRaises(ValueError): build_restage_graph(refs, FAMILY)

    def output(self, data, *, node=HANDLE_NODE, job='unit-job', size=None):
        from comfy_low.models import Output as LowOutput
        from comfy_sdk.outputs import Output
        class Transport:
            @contextmanager
            def get_asset_content(self, asset_id, **kwargs):
                yield SimpleNamespace(iter_bytes=lambda n: (data[i:i+n] for i in range(0, len(data), n)))
        model = LowOutput.model_validate({'id': 'unit-actual-output-id', 'name': 'handle.txt',
            'node_id': node, 'type': 'file', 'content_type': 'text/plain', 'size_bytes': len(data) if size is None else size,
            'job_id': job, 'hash': None, 'url': 'http://unit.invalid/output',
            'url_expires_at': '2099-01-01T00:00:00Z'})
        return Output(model, Transport())

    def job(self, outputs, status='succeeded'):
        return SimpleNamespace(id='unit-job', status=status, get_outputs=lambda node: outputs)

    def test_actual_output_stream_returns_verified_literal_not_inferred_path(self):
        expected = f'opengenjutsu_continuity/{FAMILY}/take.mp4'
        for ending in ('', '\n', '\r\n'):
            self.assertEqual(read_clip_handle(self.job([self.output((expected+ending).encode())]), FAMILY), expected)
        self.assertEqual(read_clip_handle(self.job([self.output(expected.encode(), size=0)]), FAMILY), expected)

    def test_stale_duplicate_malformed_or_oversized_handle_cannot_feed_loader(self):
        expected = f'opengenjutsu_continuity/{FAMILY}/take.mp4'.encode()
        wrong = [b'', b'../../escape.mp4', b' ' + expected, expected + b' ',
                 expected + b'\nanother.mp4', expected.replace(b'a'*32, b'b'*32), b'x'*513, b'\xff']
        for data in wrong:
            with self.subTest(data=data[:25]), self.assertRaises(ValueError):
                read_clip_handle(self.job([self.output(data, size=0)]), FAMILY)
        for outputs in ([], [self.output(expected), self.output(expected)],
                        [self.output(expected, node='stale')], [self.output(expected, job='old-job')],
                        [self.output(expected, size=len(expected)+1)], ['not-an-SDK-output']):
            with self.subTest(outputs=len(outputs)), self.assertRaises(ValueError):
                read_clip_handle(self.job(outputs), FAMILY)
        with self.assertRaises(ValueError):
            read_clip_handle(self.job([self.output(expected)], status='running'), FAMILY)
