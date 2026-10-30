"""Every model the character graph loads must be installable from the manifest."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'dependencies.json').read_text())
CATALOG = (ROOT / 'src/model_catalog.py').read_text()
VENDOR = json.loads((ROOT / 'workflows/flux3-klein-official-t2i.json').read_text())


def files_the_graph_loads() -> set[str]:
    names = set()
    for node in VENDOR.values():
        for value in (node.get('inputs') or {}).values():
            if isinstance(value, str) and value.endswith('.safetensors'):
                names.add(value)
    return names


class CharacterModelsDeclared(unittest.TestCase):
    def test_the_character_engine_has_download_entries(self):
        declared = MANIFEST.get('character_models', [])
        self.assertEqual(len(declared), 4,
                         'Create loads four files: diffusion model, encoder, upsampler, VAE')

    def test_every_file_the_graph_loads_is_declared(self):
        declared = {model['file'].split('/')[-1]
                    for model in MANIFEST['models'] + MANIFEST.get('character_models', [])}
        missing = sorted(name for name in files_the_graph_loads()
                         if name.split('/')[-1] not in declared)
        self.assertEqual(missing, [], f'not installable: {missing}')

    def test_the_downloader_knows_where_each_character_file_goes(self):
        downloader = (ROOT / 'scripts/download_models.py').read_text()
        for key in ('char_unet', 'char_clip', 'char_upsampler', 'char_vae'):
            self.assertIn(f"'{key}'", downloader, f'{key} missing from CHARACTER_FOLDERS')

    def test_character_entries_are_gated_and_pinned(self):
        for model in MANIFEST.get('character_models', []):
            download = model.get('download') or {}
            self.assertTrue(download.get('gated'), f'{model["file"]} must be flagged gated')
            self.assertRegex(download.get('revision', ''), r'^[0-9a-f]{40}$')
            self.assertIn('/resolve/' + download['revision'] + '/', download['url'])


if __name__ == '__main__':
    unittest.main()
