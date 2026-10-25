"""CPU-only contracts for compatible filename aliases and frozen Swap recipes."""
import copy
import importlib
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import config
import core
import engines
import graphs
import h3_graphs
import h3_recipe
import job_api
import take_capsule_api
from prompt_profiles import get_prompt_profile

LTX_DEFAULTS = {
    'flux_unet': config.F_UNET_KLEIN, 'flux_clip': config.F_CLIP_KLEIN,
    'flux_vae': config.F_VAE_KLEIN, 'ltx_unet': config.F_UNET_LTX,
    'ltx_clip': config.F_CLIP_LTX, 'video_vae': config.F_VAE_VID,
    'audio_vae': config.F_VAE_AUD, 'ripple_lora': config.F_LORA_RIPPLE,
}
LTX_LOADERS = {
    'flux_unet': ('70', 'unet_name'), 'flux_clip': ('71', 'clip_name'),
    'flux_vae': ('72', 'vae_name'), 'ltx_unet': ('821', 'unet_name'),
    'ltx_clip': ('1318', 'clip_name'), 'video_vae': ('822', 'vae_name'),
    'audio_vae': ('448', 'vae_name'), 'ripple_lora': ('1312', 'lora_name'),
}
H3_LOADERS = {
    'unet': ('127', 'unet_name'), 'clip': ('128', 'clip_name'),
    'video_vae': ('119', 'vae_name'), 'audio_vae': ('120', 'vae_name'),
    'turbo_lora': ('157', 'lora_name'), 'swap_lora': ('159', 'lora_name'),
    'upscaler': ('169', 'model_name'),
}


def renamed(keys):
    return {key: f'Compatible Files/{key} Renamed.safetensors' for key in keys}


def ltx_recipe():
    return job_api._build_recipe('', '', [], get_prompt_profile('ltx25-ripple'),
                                 'synthetic test direction', 19, 1.2,
                                 {'frames': 9, 'fps': 24}, 704, 384)


class CatalogTests(unittest.TestCase):
    def test_defaults_metadata_and_independent_results(self):
        catalog = importlib.import_module('model_catalog')
        expected = LTX_DEFAULTS | {'h3_' + key: value for key, value in asdict(h3_graphs.H3Models()).items()}
        with patch.object(config, 'compute_target', side_effect=AssertionError('explicit defaults must not read settings')):
            self.assertEqual(catalog.effective_bindings({}), expected)
            roles = catalog.roles()
        self.assertEqual({row['key']: row['default'] for row in roles}, expected)
        for row in roles:
            self.assertTrue({'key', 'label', 'engine', 'class_type', 'input', 'default'} <= set(row))
            self.assertIn(row['engine'], ('ltx', 'h3', 'shared'))
        roles[0]['default'] = 'changed'
        self.assertEqual(catalog.effective_bindings({}), expected)
        self.assertNotEqual(catalog.roles()[0]['default'], 'changed')

    def test_lazy_configured_resolution_and_old_target_compatibility(self):
        catalog = importlib.import_module('model_catalog')
        bindings = {'flux_unet': 'Folder/Exact Case And Spaces.safetensors'}
        with patch.object(config, 'compute_target', return_value=SimpleNamespace(model_bindings=bindings)) as target:
            actual = catalog.effective_bindings()
            target.assert_called_once_with()
            self.assertEqual(actual['flux_unet'], bindings['flux_unet'])
            self.assertEqual(catalog.effective_bindings({})['flux_unet'], LTX_DEFAULTS['flux_unet'])
        with patch.object(config, 'compute_target', return_value=SimpleNamespace()):
            self.assertEqual(catalog.effective_bindings(), catalog.effective_bindings({}))
        clean = catalog.validate_bindings(bindings)
        clean['flux_unet'] = 'other.safetensors'
        self.assertNotEqual(clean, bindings)

    def test_invalid_bindings_are_rejected_without_echoing_values(self):
        catalog = importlib.import_module('model_catalog')
        bad_names = ['', '  ', '/private/secret.safetensors', '\\private\\secret',
                     '../secret', 'a/../secret', 'a\\..\\secret', './secret',
                     'C:\\secret.safetensors', 'C:secret', 'https://secret',
                     'a\x00secret', 'a\nsecret', 'a\x7fsecret', 'a\u202esecret',
                     'x' * 513, 'a//secret', 'a/', 42, None]
        values = [None, [], 'secret', {'unknown_secret_role': 'private_secret'}]
        values += [{'flux_unet': value} for value in bad_names]
        messages = []
        for value in values:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError) as caught:
                catalog.validate_bindings(value)
            messages.append(str(caught.exception))
        self.assertEqual(len(set(messages)), 1)
        self.assertNotIn('secret', messages[0].lower())
        names = {'h3_swap_lora': ' H3/Exact Case file.safetensors '}
        self.assertEqual(catalog.validate_bindings(names), names)


class GraphBindingTests(unittest.TestCase):
    def test_ltx_builders_resolve_configured_compatible_names_without_changing_loaders(self):
        aliases = renamed(LTX_DEFAULTS)
        with patch.object(config, 'compute_target', return_value=SimpleNamespace(model_bindings=aliases)):
            frame = graphs.build_frame_edit('image', 'synthetic direction')
            ripple = graphs.build_ripple('video', 'image')
        for key, (node, input_name) in LTX_LOADERS.items():
            graph = frame if key.startswith('flux_') else ripple
            self.assertEqual(graph[node]['inputs'][input_name], aliases[key])
        self.assertEqual(frame['71']['inputs']['type'], 'flux2')
        self.assertEqual(ripple['1318']['inputs']['type'], 'ltxv')
        self.assertEqual(ripple['448']['class_type'], 'VAELoaderKJ')
        self.assertEqual(ripple['448']['inputs']['weight_dtype'], 'bf16')

    def test_ltx_explicit_mapping_and_explicit_empty_never_read_settings(self):
        aliases = renamed(LTX_DEFAULTS)
        with patch.object(config, 'compute_target', side_effect=AssertionError('ambient settings read')):
            frame = graphs.build_frame_edit('image', 'direction', model_files=aliases)
            ripple = graphs.build_ripple('video', 'image', model_files=aliases)
            default_frame = graphs.build_frame_edit('image', 'direction', model_files={})
        self.assertEqual(frame['70']['inputs']['unet_name'], aliases['flux_unet'])
        self.assertEqual(ripple['821']['inputs']['unet_name'], aliases['ltx_unet'])
        self.assertEqual(default_frame['70']['inputs']['unet_name'], LTX_DEFAULTS['flux_unet'])

    def test_h3_configured_models_and_explicit_models_precedence(self):
        aliases = renamed('h3_' + key for key in H3_LOADERS)
        with patch.object(config, 'compute_target', return_value=SimpleNamespace(model_bindings=aliases)):
            configured = h3_graphs.build_h3_recast('video', 'image', 'direction', source_frames=9)
        with patch.object(config, 'compute_target', side_effect=AssertionError('explicit H3 models read settings')):
            explicit = h3_graphs.build_h3_recast('video', 'image', 'direction', source_frames=9,
                                                  models=h3_graphs.H3Models())
        for key, (node, input_name) in H3_LOADERS.items():
            self.assertEqual(configured[node]['inputs'][input_name], aliases['h3_' + key])
            self.assertEqual(explicit[node]['inputs'][input_name], asdict(h3_graphs.H3Models())[key])
        self.assertEqual(configured['128']['inputs']['type'], 'minimax')
        self.assertEqual(configured['169']['inputs']['precision'], 'fp16')

    def test_h3_recipe_models_and_template_are_frozen_before_settings_change(self):
        aliases = renamed('h3_' + key for key in H3_LOADERS)
        with patch.object(config, 'compute_target', return_value=SimpleNamespace(model_bindings=aliases)):
            recipe = h3_recipe.make_recipe(source_width=1920, source_height=1080)
        expected = {key: aliases['h3_' + key] for key in H3_LOADERS}
        self.assertEqual(recipe['model_files'], expected)
        with patch.object(config, 'compute_target', side_effect=AssertionError('recipe read current settings')):
            frozen = h3_recipe.bind_frames(recipe, 9)
            h3_recipe.validate_recipe(frozen)
            replay = h3_graphs.build_h3_recast('video', 'image', frozen['effective_prompt'],
                                               source_frames=frozen['inference_frames'],
                                               **h3_recipe.graph_options(frozen))
        for key, (node, input_name) in H3_LOADERS.items():
            self.assertEqual(frozen['graph_template'][node]['inputs'][input_name], expected[key])
            self.assertEqual(replay[node]['inputs'][input_name], expected[key])
        broken = copy.deepcopy(frozen)
        broken['graph_template']['127']['inputs']['unet_name'] = 'different.safetensors'
        with self.assertRaises(ValueError):
            h3_recipe.validate_recipe(broken)


class LTXFrozenExecutionTests(unittest.TestCase):
    def test_submission_and_replay_options_feed_frozen_models_to_actual_engines(self):
        aliases = renamed(LTX_DEFAULTS)
        with patch.object(config, 'compute_target', return_value=SimpleNamespace(model_bindings=aliases)):
            recipe = ltx_recipe()
        self.assertEqual(recipe['model_files'], aliases)
        with patch.object(config, 'compute_target', side_effect=AssertionError('worker read current settings')):
            options = [job_api._pipeline_options(recipe, []),
                       take_capsule_api._replay_options(recipe, [], [{'start': 0, 'end': 8}])]
            for opts in options:
                with patch.object(engines, '_run_graph', return_value='local-output') as run:
                    engine = engines.LTXRippleEngine()
                    engine.edit_frame(None, 'image', 'direction', **opts['edit'])
                    frame = run.call_args.args[1]
                    engine.propagate(None, 'video', 'image', 'direction', **opts['propagate'])
                    ripple = run.call_args.args[1]
                for key, (node, input_name) in LTX_LOADERS.items():
                    graph = frame if key.startswith('flux_') else ripple
                    self.assertEqual(graph[node]['inputs'][input_name], aliases[key])
            options[0]['edit']['model_files']['flux_unet'] = 'mutation.safetensors'
            self.assertEqual(recipe['model_files'], aliases)
            self.assertEqual(options[0]['propagate']['model_files'], aliases)

    def test_core_segment_preserves_nested_model_options_without_ambient_reads(self):
        import segments
        aliases = renamed(LTX_DEFAULTS)
        with patch.object(config, 'compute_target', return_value=SimpleNamespace(model_bindings=aliases)):
            opts = job_api._pipeline_options(ltx_recipe(), [])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            anchor, output = root / 'anchor.png', root / 'output.mp4'
            anchor.write_bytes(b'synthetic anchor')
            output.write_bytes(b'synthetic output')
            client = MagicMock()
            client.assets.from_file.return_value.as_reference.return_value = {'asset': 'synthetic'}
            with patch.object(core, 'WORK', root), \
                 patch.object(config, 'compute_target', side_effect=AssertionError('worker read settings')), \
                 patch.object(segments, 'ffprobe', return_value={'fps': 24, 'frames': 9}), \
                 patch.object(segments, '_prepare', return_value=(anchor, output)), \
                 patch.object(segments, '_ffmpeg'), \
                 patch.object(engines, '_run_graph', side_effect=[str(anchor), str(output)]) as run:
                core.edit_segment(output, {'start': 0, 'end': 8}, 'direction',
                                  client=client, engine=engines.LTXRippleEngine(), **opts)
            frame, ripple = [call.args[1] for call in run.call_args_list]
        self.assertEqual(frame['70']['inputs']['unet_name'], aliases['flux_unet'])
        self.assertEqual(ripple['821']['inputs']['unet_name'], aliases['ltx_unet'])

    def test_old_partial_frozen_model_map_uses_declared_defaults_not_current_settings(self):
        with patch.object(config, 'compute_target', return_value=SimpleNamespace()):
            recipe = ltx_recipe()
        recipe['model_files'] = {'ripple_lora': 'Historical.safetensors'}
        with patch.object(config, 'compute_target', side_effect=AssertionError('legacy replay read settings')):
            opts = take_capsule_api._replay_options(recipe, [], [{'start': 0, 'end': 8}])
        expected = LTX_DEFAULTS | recipe['model_files']
        self.assertEqual(opts['edit']['model_files'], expected)
        self.assertEqual(opts['propagate']['model_files'], expected)


if __name__ == '__main__':
    unittest.main()
