"""The competition's written requirements, enforced as tests.

These are not style rules. A submission without an open-source licence, without setup
detail, or carrying private network addresses is a rejected submission, and a workflow file
that drifts from the code that runs is a false claim in the repository.

Requirement list, from the competition page:
  - built with the Comfy Developer Platform (Comfy Router and/or Comfy SDK)
  - the repo includes an open-source licence and enough setup detail to run it elsewhere
  - other tools, models or techniques are allowed and must be explained in the demo video
  - lawful, SFW, no unlicensed IP or likenesses
  - one submission per person
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

PRIVATE_ADDRESS = re.compile(
    r'\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}'
    r'|192\.168\.\d{1,3}\.\d{1,3}'
    r'|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b')
SKIP_PARTS = {'.git', '.venv', 'work', '__pycache__', 'node_modules', 'cache'}
SHIPPED_SUFFIXES = {'.py', '.js', '.mjs', '.css', '.html', '.md', '.sh', '.json', '.yaml', '.yml'}
WORKFLOW_FILES = {
    'ltx-frame-edit.api.json': 'build_frame_edit',
    'ltx-ripple.api.json': 'build_ripple',
    'h3-recast.api.json': 'build_h3_recast',
}


def shipped_files():
    for path in ROOT.rglob('*'):
        if not path.is_file() or path.suffix not in SHIPPED_SUFFIXES:
            continue
        if any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts):
            continue
        yield path


class CompetitionRequirementsTests(unittest.TestCase):
    def test_no_private_network_address_is_committed(self):
        offenders = []
        for path in shipped_files():
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            if PRIVATE_ADDRESS.search(text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f'Private addresses must not ship: {offenders}')

    def test_an_open_source_licence_ships_with_the_repository(self):
        licence = ROOT / 'LICENSE'
        self.assertTrue(licence.is_file(), 'the repository must carry a licence file')
        self.assertIn('Apache License', licence.read_text())

    def test_readme_keeps_its_licence_setup_and_workflow_pointers(self):
        readme = (ROOT / 'README.md').read_text()
        for pointer in ('Apache-2.0', 'LICENSE', 'docs/local-setup.md', 'workflows/'):
            with self.subTest(pointer=pointer):
                self.assertIn(pointer, readme)
        # The requirements say combined techniques must be explained in the demo video.
        self.assertIn('SDK', readme)

    def test_the_platform_is_the_comfy_developer_platform(self):
        transport = (ROOT / 'src' / 'comfy_transport.py').read_text()
        self.assertIn('from comfy_sdk import Comfy', transport)

    def test_workflow_files_ship_and_parse(self):
        for name in WORKFLOW_FILES:
            with self.subTest(name=name):
                graph = json.loads((ROOT / 'workflows' / name).read_text())
                self.assertTrue(graph, 'a shipped workflow must not be empty')
                for node_id, node in graph.items():
                    self.assertIn('class_type', node, f'{name} node {node_id}')
                    self.assertIn('inputs', node, f'{name} node {node_id}')
                self.assertIn('workflows/README.md', str(
                    (ROOT / 'workflows' / 'README.md')))

    def test_exported_workflows_do_not_drift_from_their_builders(self):
        """A shipped workflow that no longer matches the code is a false claim."""
        from graphs import build_frame_edit, build_ripple
        from h3_recipe import bind_frames, make_recipe
        expected = {
            'ltx-frame-edit.api.json': build_frame_edit(
                'og-source-frame-placeholder.png',
                'Replace the main performer with the character shown in the reference image.',
                reference_image='og-character-reference-placeholder.png'),
            'ltx-ripple.api.json': build_ripple(
                'og-source-video-placeholder.mp4', 'og-edited-frame-placeholder.png'),
            'h3-recast.api.json': bind_frames(
                make_recipe(source_width=1920, source_height=1080), 56,
                source_audio=True)['graph_template'],
        }
        for name, graph in expected.items():
            with self.subTest(name=name):
                self.assertEqual(json.loads((ROOT / 'workflows' / name).read_text()), graph)

    def test_no_local_paths_ship_in_the_workflows(self):
        for name in WORKFLOW_FILES:
            text = (ROOT / 'workflows' / name).read_text()
            with self.subTest(name=name):
                for leak in ('/home/', '/Users/', '127.0.0.1', 'localhost'):
                    self.assertNotIn(leak, text)


if __name__ == '__main__':
    unittest.main()
