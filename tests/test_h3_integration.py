"""HTTP → isolated H3 worker → capsule/replay, with only GPU inference mocked."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import core
import h3_api
import h3_pipeline
from h3_media import ffmpeg
from media import ffprobe


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class H3IntegrationTests(unittest.TestCase):
    def test_upload_render_capsule_replay_without_gpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / 'media'
            source, reference = root / 'input.mp4', root / 'reference.png'
            ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=64x64:rate=30:duration=0.5',
                   '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.5',
                   '-c:v', 'libx264', '-c:a', 'aac', source)
            ffmpeg('-f', 'lavfi', '-i', 'color=red:size=64x64', '-frames:v', 1,
                   '-threads', 1, reference)
            client = MagicMock()
            assets = []
            def asset(path):
                assets.append(Path(path))
                result = MagicMock()
                result.as_reference.return_value = f'uploaded-{len(assets)}'
                return result
            client.assets.from_file.side_effect = asset
            graph_box = {}
            client.workflows.from_json.side_effect = lambda graph: (graph_box.update(graph=graph) or graph)
            output = MagicMock()
            output.name = 'render.mp4'
            def download(destination):
                # This is a deliberate fake GPU render, not a visual quality claim.
                inputs = graph_box['graph']['169']['inputs']
                width, height = inputs['mode.width'], inputs['mode.height']
                ffmpeg('-i', assets[-2], '-vf', f'scale={width}:{height}', '-an', '-c:v', 'libx264',
                       '-f', 'mp4', destination)
            output.to_file.side_effect = download
            client.run.return_value.get_outputs.return_value = [output]
            app = FastAPI()
            app.include_router(h3_api.create_router(lambda: media, 1024*1024,
                               lambda: {'ready': True}, h3_pipeline.run_h3_pipeline))
            with patch.object(core, 'WORK', root), patch.object(h3_pipeline, 'make_client', return_value=client):
                with TestClient(app) as http:
                    response = http.post('/api/h3/jobs', data={'edit_prompt': '  exact user text\n'},
                                         files={'video': ('input.mp4', source.read_bytes(), 'video/mp4'),
                                                'reference_image': ('ref.png', reference.read_bytes(), 'image/png')})
                    self.assertEqual(response.status_code, 202, response.text)
                    parent = core.Job.load(response.json()['job_id'])
                    self.assertEqual(parent.status, 'done', parent.error)
                    info = ffprobe(parent.result)
                    capsule = http.get(f'/api/h3/jobs/{parent.id}/capsule').json()
                    recipe = capsule['recipe']
                    self.assertEqual((info['frames'], info['fps'], info['width'], info['height']),
                                     (12, 24, recipe['output_width'], recipe['output_height']))
                    self.assertEqual((recipe['width'], recipe['height']), (480, 480))
                    self.assertEqual((recipe['output_width'], recipe['output_height']), (960, 960))
                    self.assertEqual(capsule['recipe']['preserve_clip'], '  exact user text\n')
                    self.assertNotIn(str(root), json.dumps(capsule))
                    response = http.post(f'/api/h3/jobs/{parent.id}/replay')
                    self.assertEqual(response.status_code, 202, response.text)
                    child = core.Job.load(response.json()['job_id'])
                    self.assertEqual(child.status, 'done', child.error)
                    self.assertNotEqual(parent.result, child.result)
                    self.assertEqual(child.meta['h3_capsule']['recipe'], capsule['recipe'])
                    self.assertEqual(child.meta['h3_capsule']['parent_job_id'], parent.id)
                    self.assertEqual(client.run.call_count, 2)
                    self.assertEqual(client.close.call_count, 2)
                    # A changed result must not masquerade as the frozen take.
                    Path(parent.result).write_bytes(b'corrupt')
                    self.assertEqual(http.get(f'/api/h3/jobs/{parent.id}/capsule').status_code, 409)


if __name__ == '__main__':
    unittest.main()