"""CPU-only synthetic fixtures: graph roles/real pixels, not Qwen/GPU acceptance."""
import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuable_take as takes
import continuity_forward_api as api
from continuity_requests import ForwardRequest
import h3_prompt_generator as gen
from tests.test_timeline_artifact_contract import tensor_file

REFS = [{'__type': 'core/ASSET', 'info': {'id': name}}
        for name in ('synthetic-ninja', 'synthetic-duo')]
FRAME = {'__type': 'core/ASSET', 'info': {'id': 'synthetic-source-scene'}}
DIRECTION = ('  conserve l’action et fait apparaître le ninja de la référence picture 1 '
             'dans un nuage de fumée ; tu peux changer le plan si nécessaire.  ')


def attached_assets(graph):
    batch = graph[gen.BATCH_NODE]['inputs']
    return [graph[batch[f'image_{i}'][0]]['inputs']['image']
            for i in range(1, batch['inputcount'] + 1)]


class ContinuationGraphTests(unittest.TestCase):
    def test_three_pictures_keep_reference_order_and_separate_source_scene(self):
        graph = gen.build_prompt_graph(DIRECTION, REFS, continuation_frame=FRAME)
        self.assertEqual(attached_assets(graph), [*REFS, FRAME])
        slot = graph[gen.DIRECTION_NODE]['inputs']['string']
        self.assertIn(DIRECTION, slot)
        self.assertIn('<Picture 1>', slot)
        self.assertIn('<Picture 2>', slot)
        self.assertNotIn('<Picture 3>', slot)
        self.assertIn('last attached image is the source scene context', slot)
        self.assertIn('not a new actor/reference background', slot)
        for rule in ('casting', 'environment', 'visual style', 'ongoing action',
                     'music/song', 'voices', 'Do not invent cuts', 'permission',
                     'not a new set', 'reference-sheet background'):
            self.assertIn(rule, slot)
        self.assertNotIn('<Audio 1>', slot)
        self.assertEqual(graph[gen.MODE_NODE]['inputs']['choice'], 'from-prompt')
        self.assertEqual(graph['5833_26']['inputs']['string'].encode(),
                         gen.policy_text().encode())
        self.assertEqual(graph[gen.OUTPUT_NODE]['class_type'], 'SaveText')
        self.assertEqual(graph[gen.OUTPUT_NODE]['inputs']['text'], [gen.GENERATE_NODE, 0])
        self.assertEqual(sum(n['class_type'] == 'TextGenerate' for n in graph.values()), 1)
        self.assertEqual(graph[gen.CLIP_NODE], json.loads(gen.TEMPLATE.read_text())[gen.CLIP_NODE])

    def test_source_only_is_not_mislabelled_a_new_character(self):
        graph = gen.build_prompt_graph(DIRECTION, [], continuation_frame=FRAME)
        self.assertEqual(attached_assets(graph), [FRAME, FRAME])
        slot = graph[gen.DIRECTION_NODE]['inputs']['string']
        self.assertNotIn('<Picture 1>', slot)
        self.assertIn('last attached image is the source scene context', slot)

    def test_audio_reference_is_declared_only_when_actually_enabled(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                graph = gen.build_prompt_graph(DIRECTION, REFS, continuation_frame=FRAME,
                                               preserve_source_audio=enabled)
                slot = graph[gen.DIRECTION_NODE]['inputs']['string']
                self.assertEqual('<Audio 1>' in slot, enabled)
                if enabled:
                    self.assertIn('source song and lyrics', slot)

    def test_public_limit_bounds_original_direction_not_internal_envelope(self):
        direction = 'é' * gen.MAX_DIRECTION
        graph = gen.build_prompt_graph(direction, REFS, continuation_frame=FRAME)
        slot = graph[gen.DIRECTION_NODE]['inputs']['string']
        self.assertIn(direction, slot)
        self.assertGreater(len(slot), gen.MAX_DIRECTION)
        self.assertGreater(len(slot.encode()), gen.MAX_DIRECTION)
        with self.assertRaises(ValueError):
            gen.build_prompt_graph(direction + 'é', REFS, continuation_frame=FRAME)

    def test_no_frame_leaves_root_input_and_graph_unchanged_without_claimed_observation(self):
        root = gen.build_prompt_graph(DIRECTION, REFS)
        self.assertEqual(root[gen.DIRECTION_NODE]['inputs']['string'], DIRECTION.strip())
        self.assertEqual(attached_assets(root), REFS)
        self.assertNotIn('source scene context', root[gen.DIRECTION_NODE]['inputs']['string'])
        self.assertEqual(root, gen.build_prompt_graph(DIRECTION, REFS, continuation_frame=None))

    def test_bad_source_asset_refuses_before_any_job(self):
        with self.assertRaisesRegex(ValueError, 'committed SDK asset'):
            gen.build_prompt_graph(DIRECTION, REFS, continuation_frame='/private/source.png')


class SyntheticFrameTests(unittest.TestCase):
    """A real lossless CPU MP4 and synthetic zero-tensor sidecars, all in scratch."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / 'isolated-work'
        self.video = self.root / 'synthetic.mp4'
        self.take_id = 'a' * 32
        self.colors = [(244, 34, 12), (44, 55, 66), (88, 99, 100),
                       (120, 130, 140), (14, 28, 230)]
        pixels = b''.join(bytes(color) * (32 * 32) for color in self.colors)
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-f', 'rawvideo',
                        '-pix_fmt', 'rgb24', '-s', '32x32', '-r', '24', '-i', 'pipe:0',
                        '-frames:v', '5', '-an', '-c:v', 'libx264rgb', '-crf', '0',
                        '-threads', '1', str(self.video)], input=pixels,
                       capture_output=True, check=True, timeout=30)
        self.mctx = self.root / 'synthetic.mctx.safetensors'
        self.cond = self.root / 'synthetic.cond.safetensors'
        self_id = hashlib.sha256(self.video.read_bytes()).hexdigest()
        self.mctx.write_bytes(tensor_file({
            'video': ('F16', [1, 24, 3, 2, 2], None),
            'audio': ('F16', [1, 32, 2, 5], None)}, {
                'format': 'mctx_v1', 'self_id': self_id, 'width': '32', 'height': '32',
                'fps': '24', 'raw_frames': '9', 'delivered_frames': '5'}))
        structure = json.dumps({'__list__': [{'__list__': [
            {'__tensor__': 'embedding'}, {'__dict__': {}}]}]}).encode()
        self.cond.write_bytes(tensor_file({
            'embedding': ('F32', [1, 2, 3], None),
            'structure': ('U8', [len(structure)], structure)},
            {'format': 'obvpm_cond_v1', 'self_id': self_id}))
        takes.import_family(self.video, self.mctx, self.cond, root=self.root,
                            work=self.work, take_id=self.take_id, captured_graph=None)

    def client(self):
        from comfy_low.models import Output as LowOutput
        from comfy_sdk.outputs import Output

        # Real SDK output reader, synthetic transport bytes, never a remote job.
        data = b'synthetic prepared text'

        class SyntheticTransport:
            @contextmanager
            def get_asset_content(self, asset_id, **kwargs):
                yield SimpleNamespace(iter_bytes=lambda n: (data,))

        output = Output(LowOutput.model_validate({
            'id': 'synthetic-prompt-output', 'name': 'prompt.txt',
            'node_id': gen.OUTPUT_NODE, 'type': 'file', 'content_type': 'text/plain',
            'size_bytes': len(data), 'job_id': 'synthetic-prompt-job', 'hash': None,
            'url': 'http://synthetic.invalid/output', 'url_expires_at': '2099-01-01T00:00:00Z',
        }), SyntheticTransport())
        client = Mock()
        client.workflows.from_json.side_effect = lambda graph: graph
        client.run.return_value = SimpleNamespace(
            status='succeeded', id='synthetic-prompt-job', get_outputs=lambda node: [output])
        self.uploaded = []

        def upload(path):
            path = Path(path)
            with Image.open(path) as image:
                self.uploaded.append((path, image.convert('RGB').getpixel((16, 16))))
            return SimpleNamespace(as_reference=lambda: FRAME)

        client.assets.from_file.side_effect = upload
        return client

    def test_each_mode_extracts_actual_first_or_last_pixels_then_runs_one_refiner(self):
        for mode, expected in (('forward', self.colors[-1]), ('prepend', self.colors[0]),
                               ('bridge', self.colors[-1])):
            with self.subTest(mode=mode):
                client = self.client()
                before = self.video.read_bytes()
                result = api.refine_continuation_prompt(
                    client, self.work, self.take_id, DIRECTION, REFS,
                    mode=mode, preserve_source_audio=True)
                self.assertEqual(result, 'synthetic prepared text')
                client.run.assert_called_once()
                self.assertEqual(self.uploaded[0][1], expected)
                self.assertFalse(self.uploaded[0][0].exists(), 'temporary frame must be removed')
                graph = client.run.call_args.args[0]
                self.assertEqual(attached_assets(graph), [*REFS, FRAME])
                self.assertIn(DIRECTION, graph[gen.DIRECTION_NODE]['inputs']['string'])
                self.assertIn('<Audio 1>', graph[gen.DIRECTION_NODE]['inputs']['string'])
                self.assertEqual(self.video.read_bytes(), before)

    def test_corrupt_family_refuses_before_extraction_upload_or_run(self):
        family = takes.get_validated_family(self.work, self.take_id)
        family.video.chmod(0o600)
        family.video.write_bytes(b'synthetic corruption')
        client = self.client()
        with patch.object(api, '_extract_continuation_frame') as extract:
            with self.assertRaises(ValueError):
                api.refine_continuation_prompt(client, self.work, self.take_id, DIRECTION, REFS)
        extract.assert_not_called()
        client.assets.from_file.assert_not_called()
        client.run.assert_not_called()

    def test_invalid_mode_refuses_before_upload_or_run(self):
        client = self.client()
        with self.assertRaises(ValueError):
            api.refine_continuation_prompt(client, self.work, self.take_id, DIRECTION, REFS,
                                           mode='root')
        client.assets.from_file.assert_not_called()
        client.run.assert_not_called()

    def test_failed_extraction_is_closed_and_cleans_private_directory(self):
        client = self.client()
        real_run = subprocess.run
        directories = []

        def fail_decode(command, **kwargs):
            if command[0] == 'ffmpeg':
                directories.append(Path(command[-1]).parent)
                raise subprocess.TimeoutExpired('ffmpeg', 60)
            return real_run(command, **kwargs)

        with patch.object(api.subprocess, 'run', side_effect=fail_decode):
            with self.assertRaisesRegex(ValueError, 'source scene'):
                api.refine_continuation_prompt(client, self.work, self.take_id, DIRECTION, REFS)
        self.assertEqual(len(directories), 1)
        self.assertFalse(directories[0].exists())
        client.assets.from_file.assert_not_called()
        client.run.assert_not_called()


class ForwardGroundingWiringTests(unittest.TestCase):
    def test_preflight_audio_context_reaches_refiner_and_submit_only_when_present(self):
        for context in (None, {'policy': 'original-source-v1', 'synthetic': True}):
            with self.subTest(context=context):
                client = Mock()
                client.assets.from_file.return_value.as_reference.side_effect = REFS
                preflight = Mock(return_value=context)
                with patch.object(api, 'parent_references', return_value=[Path('/r1.png'), Path('/r2.png')]), \
                     patch.object(api, 'precheck_source_audio') as audio_guard, \
                     patch.object(api, 'refine_continuation_prompt', return_value='synthetic prepared') as refine, \
                     patch.object(api, 'submit_forward', return_value={'status': 'done'}) as submit:
                    runner = api.make_forward_runner(client_factory=lambda: client,
                        models_factory=lambda: 'synthetic-models', fingerprint='synthetic-target',
                        work_root='/synthetic-ops', preflight=preflight)
                    runner('/synthetic-work', 'a' * 32, ForwardRequest(
                        request_id='b' * 32, prompt=DIRECTION, seed=7, raw_frames=158))
                audio_guard.assert_called_once_with('/synthetic-work', context)
                self.assertEqual(refine.call_args.args, (client, '/synthetic-work', 'a' * 32,
                                                         DIRECTION, REFS))
                self.assertEqual(refine.call_args.kwargs['preserve_source_audio'], context is not None)
                self.assertEqual(submit.call_args.kwargs['references'], REFS)
                self.assertIs(submit.call_args.kwargs['audio_context'], context)
                client.run.assert_not_called()

    def test_preflight_refusal_happens_before_client_extraction_upload_or_refiner(self):
        factory = Mock()
        with patch.object(api, 'parent_references', return_value=[Path('/ref.png')]), \
             patch.object(api, '_extract_continuation_frame') as extract, \
             patch.object(api, 'refine_continuation_prompt') as refine:
            runner = api.make_forward_runner(client_factory=factory,
                models_factory=lambda: 'synthetic-models', fingerprint='synthetic-target',
                work_root='/synthetic-ops', preflight=Mock(side_effect=ValueError('preflight refused')))
            with self.assertRaisesRegex(ValueError, 'preflight refused'):
                runner('/synthetic-work', 'a' * 32, ForwardRequest(
                    request_id='b' * 32, prompt=DIRECTION, seed=7, raw_frames=158))
        factory.assert_not_called()
        extract.assert_not_called()
        refine.assert_not_called()


if __name__ == '__main__':
    unittest.main()
