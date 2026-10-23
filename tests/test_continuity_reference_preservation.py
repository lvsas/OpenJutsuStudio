"""CPU-only reference lifecycle proofs using isolated, synthetic Take families."""
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_context as ctx
import continuity_forward_api as api
import continuity_pipeline as pipeline
import continuable_take as ct
from tests import test_continuable_take as take_tests


class ReferencePreservationTests(unittest.TestCase):
    setUp = take_tests.ContinuableTakeTests.setUp
    do_import = take_tests.ContinuableTakeTests.do_import
    directory = take_tests.ContinuableTakeTests.directory
    write_mctx = take_tests.ContinuableTakeTests.write_mctx

    def prepare(self, *, inherited=True):
        self.first = self.root / 'one.png'
        self.second = self.root / 'two.jpg'
        self.first.write_bytes(b'ONE')
        self.second.write_bytes(b'TWO')
        self.do_import(references=(self.first, self.second) if inherited else ())
        self.frozen = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        app = FastAPI()
        app.include_router(api.create_forward_router(lambda: self.work))
        self.client = TestClient(app)
        self.url = f'/api/continuity/takes/{self.take_id}/references'

    def upload(self, payload=b'THREE', name='three.webp', method='post', position=''):
        return getattr(self.client, method)(self.url + position,
                                            files={'image': (name, payload, 'image/webp')})

    def assert_payloads(self, expected):
        listing = self.client.get(self.url)
        self.assertEqual(listing.status_code, 200, listing.text)
        entries = listing.json()['references']
        self.assertEqual([entry['index'] for entry in entries], list(range(1, len(expected) + 1)))
        self.assertEqual([self.client.get(entry['url']).content for entry in entries], expected)
        self.assertEqual([entry['sha256'] for entry in entries],
                         [hashlib.sha256(payload).hexdigest() for payload in expected])

    def assert_source_unchanged(self):
        self.assertEqual({p.name: p.read_bytes() for p in self.directory.iterdir()}, self.frozen)
        self.assertEqual(self.first.read_bytes(), b'ONE')
        self.assertEqual(self.second.read_bytes(), b'TWO')

    def test_two_inherited_then_add_preserves_all_three_and_the_source(self):
        self.prepare()
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(len(response.json()['references']), 3)
        self.assert_payloads([b'ONE', b'TWO', b'THREE'])
        self.assert_source_unchanged()

    def test_first_delete_copies_inheritance_and_keeps_the_other_reference(self):
        self.prepare()
        response = self.client.delete(self.url + '/1')
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_payloads([b'TWO'])
        self.assert_source_unchanged()

    def test_delete_all_is_explicit_empty_not_resurrected_inheritance(self):
        self.prepare()
        self.assertEqual(self.client.delete(self.url + '/2').status_code, 200)
        self.assertEqual(self.client.delete(self.url + '/1').status_code, 200)
        self.assert_payloads([])
        self.assertEqual(api.parent_references(self.work, self.take_id), [])
        self.assertEqual(self.client.get(self.url + '/1').status_code, 404)
        self.assert_source_unchanged()

    def test_replace_preserves_order_other_bytes_and_source(self):
        self.prepare()
        response = self.upload(b'REPLACED', method='put', position='/2')
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_payloads([b'ONE', b'REPLACED'])
        self.assert_source_unchanged()

    def test_existing_prepared_context_never_reads_origin_or_inherited_take(self):
        self.prepare()
        self.assertEqual(self.upload().status_code, 201)
        with patch.object(api, 'inherited_references', side_effect=AssertionError('origin read')):
            self.assertEqual(self.upload(b'FOUR').status_code, 201)
            self.assertEqual(self.client.delete(self.url + '/1').status_code, 200)
            self.assert_payloads([b'TWO', b'THREE', b'FOUR'])

    def test_declared_identity_corruption_cannot_become_an_empty_editable_context(self):
        self.prepare()
        reference = self.directory / 'reference-1.png'
        reference.chmod(0o600)
        reference.write_bytes(b'CORRUPTED')
        for method in ('post', 'delete', 'put'):
            with self.subTest(method=method):
                response = (self.client.delete(self.url + '/1') if method == 'delete'
                            else self.upload(method=method, position='/1' if method == 'put' else ''))
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn('no longer matches', response.json()['detail'])
        self.assertFalse((self.work / 'timeline' / 'continuity-contexts' /
                          self.take_id / 'context.json').exists())
        self.assertEqual(self.client.get(self.url).status_code, 409)

    def test_prepared_hash_mismatch_is_refused_for_reads_and_edits(self):
        self.prepare()
        self.assertEqual(self.upload().status_code, 201)
        ctx.context_references(self.work, self.take_id)[0].write_bytes(b'CORRUPTED')
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assertEqual(self.client.get(self.url + '/1').status_code, 409)
        self.assertEqual(self.upload().status_code, 422)
        self.assertEqual(self.client.delete(self.url + '/1').status_code, 422)

    def test_missing_historical_references_allows_upload_and_delete_again(self):
        self.prepare(inherited=False)
        with patch('core.Job.load', side_effect=KeyError('historical job')):
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.client.delete(self.url + '/1').status_code, 200)
            self.assert_payloads([])

    def test_missing_historical_references_delete_is_unknown_reference_not_origin_error(self):
        self.prepare(inherited=False)
        with patch('core.Job.load', side_effect=KeyError('historical job')):
            response = self.client.delete(self.url + '/1')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail'], 'Unknown reference')
        self.assert_payloads([])

    def test_unknown_take_cannot_create_a_context(self):
        self.prepare()
        self.url = '/api/continuity/takes/' + 'f' * 32 + '/references'
        self.assertEqual(self.upload().status_code, 404)
        self.assertEqual(self.client.delete(self.url + '/1').status_code, 404)

    def test_legacy_origin_preserves_every_reference_in_order(self):
        self.prepare(inherited=False)
        legacy = SimpleNamespace(meta={'h3_references': [str(self.first), str(self.second)]})
        with patch('core.Job.load', return_value=legacy):
            self.assert_payloads([b'ONE', b'TWO'])
            self.assertEqual(self.upload().status_code, 201)
        self.assert_payloads([b'ONE', b'TWO', b'THREE'])

    def test_reference_image_uses_list_length_not_sixty_four(self):
        self.prepare(inherited=False)
        for index in range(65):
            ctx.add_reference(self.work, self.take_id, str(index).encode(), '.png')
        self.assertEqual(self.client.get(self.url + '/65').content, b'64')
        for index in (-1, 0, 66):
            self.assertEqual(self.client.get(self.url + f'/{index}').status_code, 404)

    def test_collector_imports_all_copied_references_inside_root_and_child_carries_all(self):
        self.prepare()
        self.assertEqual(self.upload().status_code, 201)
        paths = api.parent_references(self.work, self.take_id)
        child_id = 'c' * 32
        destination = self.work / 'media' / 'isolated-forward'

        def download(remote_job, node, folder):
            folder.mkdir(parents=True)
            for source, name in ((self.video, 'take.mp4'),
                                 (self.mctx, 'take.mctx.safetensors'),
                                 (self.cond, 'take.cond.safetensors')):
                (folder / name).write_bytes(source.read_bytes())

        with patch.object(pipeline, 'download_h3_artifacts', side_effect=download), \
                patch.object(pipeline, 'import_family', wraps=ct.import_family) as importer:
            collect = pipeline.collect_forward(self.work, destination, compiled_graph=self.graph,
                                               reference_paths=paths)
            result = collect(SimpleNamespace(id='remote-child'), None, child_id)
        self.assertEqual(result, child_id)
        carried = importer.call_args.kwargs['references']
        self.assertIsInstance(carried, tuple)
        self.assertEqual([p.name for p in carried],
                         ['reference-1.png', 'reference-2.jpg', 'reference-3.webp'])
        self.assertTrue(all(p.parent == destination.resolve() for p in carried))
        self.assertEqual([p.read_bytes() for p in api.parent_references(self.work, child_id)],
                         [b'ONE', b'TWO', b'THREE'])
        self.assert_source_unchanged()

    def test_submit_passes_every_reference_path_to_its_collector(self):
        from tests.test_continuity_pipeline import MODELS, family
        self.prepare()
        paths = api.parent_references(self.work, self.take_id)
        with patch.object(pipeline, 'get_validated_family', return_value=family()), \
                patch.object(pipeline, 'restage_parent', return_value='isolated/take.mp4'), \
                patch.object(pipeline, 'build_latent_continuity', return_value=self.graph), \
                patch.object(pipeline, 'create_operation'), \
                patch.object(pipeline, 'execute_operation', return_value={'status': 'succeeded'}), \
                patch.object(pipeline, 'collect_forward') as collector:
            pipeline.submit_forward(
                self.work, self.take_id,
                SimpleNamespace(prompt='continue', seed=7, raw_frames=56),
                client=object(), models=MODELS, references=[{'ref': 1}, {'ref': 2}],
                target_fingerprint='f' * 64, work_root=self.work / 'operations',
                reference_paths=paths, inventory=lambda graph: ([], []))
        self.assertEqual(collector.call_args.kwargs['reference_paths'], paths)

    def test_explicit_empty_collector_sequence_does_not_reuse_singular_argument(self):
        self.prepare()
        destination = self.work / 'media' / 'empty-forward'
        with patch.object(pipeline, 'download_h3_artifacts',
                          side_effect=lambda *args: destination.mkdir(parents=True)), \
                patch.object(pipeline, 'import_family', return_value=SimpleNamespace(take_id='c' * 32)) as importer:
            collect = pipeline.collect_forward(self.work, destination, compiled_graph=self.graph,
                                               reference_path=self.first, reference_paths=[])
            collect(SimpleNamespace(id='remote-child'), None, 'c' * 32)
        self.assertEqual(importer.call_args.kwargs['references'], ())

    def test_legacy_singular_collector_argument_still_works(self):
        self.prepare()
        destination = self.work / 'media' / 'singular-forward'
        with patch.object(pipeline, 'download_h3_artifacts',
                          side_effect=lambda *args: destination.mkdir(parents=True)), \
                patch.object(pipeline, 'import_family', return_value=SimpleNamespace(take_id='c' * 32)) as importer:
            collect = pipeline.collect_forward(self.work, destination, compiled_graph=self.graph,
                                               reference_path=self.first)
            collect(SimpleNamespace(id='remote-child'), None, 'c' * 32)
        self.assertEqual([p.read_bytes() for p in importer.call_args.kwargs['references']], [b'ONE'])


if __name__ == '__main__':
    unittest.main()
