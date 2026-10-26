"""Real graph scopes are installation requirements, not historical template unions."""
import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_dependencies as checker

MODEL_FIELDS = {'unet_name', 'clip_name', 'vae_name', 'lora_name', 'model_name', 'quantization', 'attention_mode'}


def inventory(graph):
    result = {}
    for node in graph.values():
        info = result.setdefault(node['class_type'], {'python_module':'test-fixture', 'input':{'required':{}}})
        for key, value in node['inputs'].items():
            if key in MODEL_FIELDS and isinstance(value, str):
                options = info['input']['required'].setdefault(key, [[], {}])[0]
                if value not in options:
                    options.append(value)
    return result


class ExecutorScopeTests(unittest.TestCase):
    def setUp(self):
        self.manifest = checker.load_manifest()

    def test_h3_only_does_not_require_ltx_characters_or_experimental_nodes(self):
        info = inventory(checker.runtime_graph('h3'))
        report = checker.check_swap(info, self.manifest, 'h3')
        self.assertFalse(checker.required_missing(report), report)
        self.assertNotIn('VAELoaderKJ', info)
        self.assertEqual(report['scope'], 'h3')
        self.assertEqual(report['checked_models'], 7)
        self.assertIn('MiniMaxH3AddGuide', info)

    def test_ltx_scope_keeps_first_frame_and_exact_audio_loader(self):
        info = inventory(checker.runtime_graph('ltx'))
        report = checker.check_swap(info, self.manifest, 'ltx')
        self.assertFalse(checker.required_missing(report), report)
        self.assertEqual(report['checked_models'], 8)
        self.assertIn('EmptyFlux2LatentImage', info)
        self.assertIn('VAELoaderKJ', info)
        # An audio VAE listed in VAELoader alone cannot satisfy VAELoaderKJ.
        info['VAELoaderKJ']['input']['required']['vae_name'] = [[], {}]
        self.assertTrue(checker.required_missing(checker.check_swap(info, self.manifest, 'ltx')))

    def test_missing_node_attribution_and_core_are_graph_specific(self):
        info = inventory(checker.runtime_graph('h3'))
        del info['MinimaxH3LatentUpscaler3D']
        report = checker.check_swap(info, self.manifest, 'h3')
        self.assertIn('MiniMaxH3-LatentUpscaler', report['missing_nodes'])
        del info['MiniMaxH3ReferenceToVideo']
        self.assertIn('MiniMaxH3ReferenceToVideo', checker.check_swap(info, self.manifest, 'h3')['missing_core_nodes'])

    def test_missing_vision_pack_and_incompatible_choices_are_explicit(self):
        graph = checker.runtime_graph('h3', descriptions=True)
        info = inventory(graph)
        good = checker.check_swap(info, self.manifest, 'h3', descriptions=True)
        self.assertFalse(checker.required_missing(good), good)
        self.assertTrue(good['provisioning_notes'])  # No false claim of HF file presence.
        self.assertIn('not verified', ' '.join(good['provisioning_notes']).lower())
        del info['AILab_QwenVL']
        missing = checker.check_swap(info, self.manifest, 'h3', descriptions=True)
        self.assertIn('ComfyUI-QwenVL', missing['missing_nodes'])
        info = inventory(graph)
        info['AILab_QwenVL']['input']['required']['quantization'] = [['unsupported'], {}]
        self.assertTrue(checker.required_missing(checker.check_swap(info, self.manifest, 'h3', descriptions=True)))

    def test_unknown_inventory_is_distinct_from_known_empty(self):
        info = inventory(checker.runtime_graph('h3'))
        info['CLIPLoader']['input']['required']['clip_name'] = ['UNRECOGNIZED', {}]
        unknown = checker.check_swap(info, self.manifest, 'h3')
        self.assertTrue(unknown['unknown_inventory'])
        info['CLIPLoader']['input']['required']['clip_name'] = [[], {}]
        empty = checker.check_swap(info, self.manifest, 'h3')
        self.assertFalse(empty['unknown_inventory'])
        self.assertTrue(empty['missing_models'])
        self.assertTrue(checker.required_missing(unknown))

    def test_every_runtime_class_has_one_declared_owner_and_pack_install_source(self):
        core = set(sum([self.manifest['core_nodes'][key] for key in ('from_core','from_comfy_extras')], []))
        owners = {}
        for pack in self.manifest['comfyui_packs']:
            for node in pack['nodes']:
                owners.setdefault(node, []).append(pack)
        for node in {n['class_type'] for n in checker.runtime_graph('all', descriptions=True).values()}:
            with self.subTest(node=node):
                if node in core:
                    self.assertNotIn(node, owners)
                else:
                    self.assertEqual(len(owners.get(node, [])), 1)
                    pack = owners[node][0]
                    self.assertTrue(pack['source'].startswith('https://github.com/'))
                    install = pack['install']
                    if install['kind'] == 'git':
                        self.assertRegex(install['revision'], r'^[0-9a-f]{40}$')
                    else:
                        self.assertEqual(install['kind'], 'registry')
                        self.assertRegex(install['package_sha256'], r'^[0-9a-f]{64}$')

    def test_graph_construction_ignores_saved_target_bindings(self):
        import config
        with mock.patch.object(config, 'compute_target', side_effect=AssertionError('saved config')):
            graph = checker.runtime_graph('all', descriptions=True)
        self.assertTrue(graph)

    def test_cli_snapshot_is_offline_and_machine_readable(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as root:
            path = Path(root) / 'inventory.json'
            path.write_text(json.dumps(inventory(checker.runtime_graph('h3'))))
            output = io.StringIO()
            with mock.patch.object(checker, 'fetch_object_info', side_effect=AssertionError('network')), contextlib.redirect_stdout(output):
                status = checker.main(['--engine', 'h3', '--object-info', str(path), '--json'])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())['inventory_source'], 'snapshot')

    def test_cli_rejects_credentials_without_network_or_leaking_them(self):
        output = io.StringIO()
        with mock.patch.object(checker, 'fetch_object_info', side_effect=AssertionError('network')), contextlib.redirect_stderr(output):
            status = checker.main(['--engine', 'h3', '--host', 'https://user:PRIVATE-fixture@example.org'])
        self.assertEqual(status, 2)
        self.assertNotIn('PRIVATE-fixture', output.getvalue())

    def test_cli_cannot_mix_swap_and_advanced_scopes(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                checker.main(['--engine', 'h3', '--feature', 'characters'])
            with self.assertRaises(SystemExit):
                checker.main(['--engine', 'ltx', '--with-descriptions'])

    def test_vision_manifest_matches_runtime_defaults_without_changing_models(self):
        from h3_preserve import VISION_MODEL, VISION_QUANTIZATION, VISION_NODE
        role = self.manifest['vision_description']
        self.assertEqual(role['model_name'], VISION_MODEL)
        self.assertEqual(role['quantization'], VISION_QUANTIZATION)
        self.assertEqual(role['node'], VISION_NODE)
        self.assertRegex(role['revision'], r'^[0-9a-f]{40}$')
        self.assertEqual(role['local_dir'], 'LLM/Qwen/Qwen3-VL-2B-Instruct')


if __name__ == '__main__':
    unittest.main()
