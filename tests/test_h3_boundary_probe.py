"""Self-contained harness tests; no upstream checkout, torch or network needed.

The temporary reference texts below are deliberately synthetic, NOT vendored
upstream implementations. Real upstream behavior is checked by the explicit CLI
run, whose source hashes and observations live in its JSON output.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_h3_native_boundaries.py'
spec = importlib.util.spec_from_file_location('boundary_probe_under_test', SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ReferenceExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'reference.py'

    def source(self, text):
        self.path.write_text(text)
        return self.path

    def test_exact_selected_function_executes_not_top_level_imports(self):
        text = ('import nonexistent_gpu_package\nraise RuntimeError("must not execute")\n'
                'BASE = 7 / 2\ndef selected(value):\n    return value * BASE + 13\n'
                'def unrelated():\n    raise RuntimeError("not selected")\n')
        namespace, provenance = probe.extract_reference(self.source(text), ('selected',), ('BASE',))
        self.assertEqual(namespace.selected(2), 20)
        self.assertFalse(hasattr(namespace, 'unrelated'))
        self.assertEqual(provenance['sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(provenance['definition_lines']['selected'], [4, 5])
        self.assertEqual(provenance['size_bytes'], len(text.encode()))

    def test_calls_between_selected_functions_keep_same_globals(self):
        namespace, _ = probe.extract_reference(self.source(
            'def first(n):\n    return second(n)\n'
            'def second(n):\n    return n + dependency\n'),
            ('first', 'second'), globals_={'dependency': 23})
        self.assertEqual(namespace.first(4), 27)

    def test_missing_and_duplicate_definitions_refused(self):
        for text in ('def other(): pass\n', 'def requested(): pass\ndef requested(): pass\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Missing or duplicate'):
                probe.extract_reference(self.source(text), ('requested',))

    def test_non_arithmetic_constant_and_decorator_refused(self):
        for text, constants in (('BASE = danger()\ndef selected(): pass\n', ('BASE',)),
                                ('@danger\ndef selected(): pass\n', ())):
            with self.subTest(text=text), self.assertRaises(ValueError):
                probe.extract_reference(self.source(text), ('selected',), constants)

    def test_source_size_bound(self):
        path = self.source('#' * (probe.MAX_SOURCE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, '1 MiB'):
            probe.extract_reference(path, ('selected',))

    def test_all_source_paths_are_explicit_and_each_role_is_extracted(self):
        paths = []
        groups = ((probe.PINS_FUNCTIONS, ()),
                  (probe.MASKED_FUNCTIONS, probe.MASKED_CONSTANTS),
                  (probe.FRAMES_FUNCTIONS, probe.FRAMES_CONSTANTS))
        for i, (functions, constants) in enumerate(groups):
            path = Path(self.temp.name) / f'synthetic-{i}.py'
            text = ''.join(f'{name} = 1\n' for name in constants)
            text += ''.join(f'def {name}(*args, **kwargs):\n    return {name!r}\n' for name in functions)
            path.write_text(text)
            paths.append(path)
        ref = probe.load_reference(*paths)
        self.assertEqual(ref.pins.slice_step(), 'slice_step')
        self.assertEqual(ref.masked.handover_frames(), 'handover_frames')
        self.assertEqual(ref.frames.audio_total(), 'audio_total')
        self.assertEqual(set(ref.sources), {'pins', 'masked', 'frames'})
        self.assertTrue(all(len(p['sha256']) == 64 for p in ref.sources.values()))

    def test_cli_requires_all_three_sources(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        for flag in ('--pins-source', '--masked-source', '--frames-source'):
            self.assertIn(flag, result.stderr)


class ShapeOnlyTests(unittest.TestCase):
    def test_slice_coordinates_and_clone_preserve_source_provenance(self):
        source = probe.ShapeTensor((1, 32, 2, 263), 'source-audio')
        window = source[:1, ..., 199:264].clone()
        self.assertEqual(window.shape, (1, 32, 2, 64))
        self.assertEqual(window.reads[-1]['slice'][-1], [199, 263, 1])
        target = probe.ShapeTensor((1, 32, 2, 320), 'target-audio')
        with self.assertRaisesRegex(ValueError, 'shape mismatch'):
            target[..., :65] = window
        self.assertEqual(target.writes, [])
        target[..., 256:320] = window
        self.assertEqual(target.writes[0]['target_slice'][-1], [256, 320, 1])
        self.assertEqual(target.writes[0]['source_reads'], window.reads)

    def test_video_profile_broadcast_and_negative_tail_slice(self):
        target = probe.ShapeTensor((1, 16, 47, 2, 3))
        profile = probe.ProfileTorch.tensor([0.] * 11 + [.6]).view(1, 1, 12, 1, 1)
        target[:, :, -12:] = profile
        self.assertEqual(target.writes[0]['target_slice'][2], [35, 47, 1])
        self.assertEqual(target.writes[0]['profile_values'][-1], .6)
        self.assertEqual(profile.flatten()[-1].item(), .6)
        self.assertEqual(profile.flatten().tolist(), [0.] * 11 + [.6])

    def test_scalar_mask_writes_and_profile_bounds(self):
        mask = probe.ProfileTorch.ones((1, 1, 2, 65))
        mask[..., :65] = 0.0
        self.assertEqual(mask.writes[0]['scalar'], 0.)
        with self.assertRaisesRegex(ValueError, 'bound'):
            probe.ProfileTorch.full((4097,), 0.)
        with self.assertRaisesRegex(ValueError, 'No numerical payload'):
            mask.tolist()

    def test_nested_import_double_restores_existing_modules_on_failure(self):
        original = ModuleType('comfy-original')
        for old_nested in (None, ModuleType('nested-original')):
            with patch.dict(sys.modules, {'comfy': original, 'comfy.nested_tensor': old_nested}):
                with self.assertRaisesRegex(RuntimeError, 'expected'):
                    with probe.scoped_nested_tensor():
                        nested = importlib.import_module('comfy.nested_tensor')
                        self.assertIs(nested.NestedTensor, probe.NestedShape)
                        raise RuntimeError('expected')
                self.assertIs(sys.modules['comfy'], original)
                self.assertIs(sys.modules['comfy.nested_tensor'], old_nested)

    def test_nested_import_double_restores_absence(self):
        with patch.dict(sys.modules):
            sys.modules.pop('comfy', None)
            sys.modules.pop('comfy.nested_tensor', None)
            with probe.scoped_nested_tensor():
                self.assertIn('comfy.nested_tensor', sys.modules)
            self.assertNotIn('comfy', sys.modules)
            self.assertNotIn('comfy.nested_tensor', sys.modules)

    def test_importing_script_does_not_import_torch_or_comfy(self):
        code = ('import runpy, sys; runpy.run_path(sys.argv[1], run_name="not_main"); '
                'assert "torch" not in sys.modules; assert "comfy" not in sys.modules')
        result = subprocess.run([sys.executable, '-c', code, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_selected_function_can_record_assignments(self):
        # Synthetic function tests the AST -> assignment trace path, not H3 math.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tiny.py'
            path.write_text('def selected(target, source):\n'
                            '    target[..., 3:8] = source[..., 1:6].clone()\n'
                            '    return target\n')
            namespace, _ = probe.extract_reference(path, ('selected',))
            result = namespace.selected(probe.ShapeTensor((1, 10), 'dst'),
                                        probe.ShapeTensor((1, 7), 'src'))
        self.assertEqual(result.writes[0]['target_slice'][-1], [3, 8, 1])
        self.assertEqual(result.writes[0]['source_reads'][-1]['slice'][-1], [1, 6, 1])

    def test_two_pins_are_applied_together_and_phase_uses_the_whole_stack(self):
        frames = SimpleNamespace(steps_for_frames=lambda raw: 47, audio_total=lambda raw: 320)
        pins = [{'video': probe.ShapeTensor((1, 7, 12, 2, 3)),
                 'audio': probe.ShapeTensor((1, 13, 2, 65))} for _ in range(2)]
        seen = []
        def apply(latent, actual, audio_feather_ticks):
            self.assertEqual(actual, pins)
            seen.append(actual)
            return {'samples': latent['samples'], 'noise_mask': latent['samples']}
        def phase(actual, raw):
            self.assertEqual(actual, pins)
            return 0.25
        ref = SimpleNamespace(frames=frames, masked=SimpleNamespace(apply_masked_pins=apply),
                              pins=SimpleNamespace(pins_audio_phase=phase), log=probe.TraceLog())
        self.assertEqual(probe.apply_pins(ref, pins, 158)['child_audio_phase'], 0.25)
        self.assertEqual(len(seen), 1)
        with self.assertRaises(ValueError):
            probe.apply_pins(ref, [], 158)

    def test_apply_probe_retains_source_channels_and_spatial_grid(self):
        # Deliberately synthetic reference API: verifies harness shape plumbing.
        frames = SimpleNamespace(steps_for_frames=lambda raw: 12, audio_total=lambda raw: 65)
        def apply(latent, pins, audio_feather_ticks):
            self.assertEqual(audio_feather_ticks, 0)
            video, audio = latent['samples'].tensors
            self.assertEqual(video.shape, (1, 7, 12, 68, 120))
            self.assertEqual(audio.shape, (1, 13, 2, 65))
            return {'samples': latent['samples'], 'noise_mask': latent['samples']}
        ref = SimpleNamespace(frames=frames, masked=SimpleNamespace(apply_masked_pins=apply),
                              pins=SimpleNamespace(pins_audio_phase=lambda pins, raw: 0.),
                              log=probe.TraceLog())
        pin = {'video': probe.ShapeTensor((1, 7, 12, 68, 120)),
               'audio': probe.ShapeTensor((1, 13, 2, 65))}
        self.assertEqual(probe.apply_pin(ref, pin, 39)['audio_writes'], [])


class HeaderOnlyTests(unittest.TestCase):
    def test_work_scan_reads_only_bounded_header_and_retains_real_shapes(self):
        # A complete, explicitly synthetic safetensors envelope; payload is never read.
        header = {'__metadata__': {'raw_frames': '39', 'delivered_frames': '39', 'audio_phase': '0'},
                  'video': {'dtype': 'F32', 'shape': [1, 2, 12, 1, 1], 'data_offsets': [0, 96]},
                  'audio': {'dtype': 'F32', 'shape': [1, 2, 2, 65], 'data_offsets': [96, 1136]}}
        raw = json.dumps(header).encode()
        envelope = struct.pack('<Q', len(raw)) + raw
        blob = envelope + bytes(1136)
        class GuardedReader(io.BytesIO):
            def read(self, n: int | None = -1):
                if n is None or n < 0 or self.tell() + n > len(envelope):
                    raise AssertionError('Tensor payload read attempted')
                return super().read(n)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.mctx.safetensors'
            path.write_bytes(blob)
            with patch.object(Path, 'open', return_value=GuardedReader(blob)):
                states, scan = probe.measured_states(directory)
        self.assertEqual(scan['candidate_headers'], 1)
        self.assertEqual(scan['payload_bytes_read'], 0)
        self.assertEqual(scan['errors'], [])
        self.assertEqual(states[0]['video_shape'], [1, 2, 12, 1, 1])
        self.assertEqual(states[0]['fixture_kind'], 'measured_header_shapes')
        self.assertEqual(states[0]['project_av_state']['audio_ticks'], 65)

    def test_dependency_recipe_parser_is_bounded_and_explicit(self):
        self.assertEqual(probe.parse_pins_dependency({'pins': '[{"place":"before"}]'}),
                         [{'place': 'before'}])
        self.assertEqual(probe.parse_pins_dependency({}), [])
        for value in ('{}', 'x' * 65537, [{}] * 17):
            with self.assertRaises(ValueError):
                probe.parse_pins_dependency({'pins': value})


if __name__ == '__main__':
    unittest.main()
