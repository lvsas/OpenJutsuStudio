#!/usr/bin/env python3
"""Offline numeric/control-flow oracle over explicitly supplied trusted sources.

No upstream module is imported or vendored. Only named top-level AST function
bodies and the small named arithmetic constants are compiled, unchanged. Source
arguments are executable Python, NOT an untrusted-code sandbox. Tensor doubles
record shapes, slice coordinates and writes, not values or GPU/render quality.
The sole module-import double (comfy.nested_tensor) is scoped and restored.

Run: PYTHONPATH=src .venv/bin/python scripts/probe_h3_native_boundaries.py \
    --pins-source /reference/nodes_pins.py --masked-source /reference/nodes_masked.py \
    --frames-source /reference/frames.py [--work /project/store]
JSON goes to stdout; this program does not write files or submit jobs.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

MAX_SOURCE_BYTES = 1024 * 1024
MAX_RAW_FRAMES = 4096
RAW_CASES = (56, 124, 158, 192, 362)
TARGET_CASES = (56, 124, 158, 192)
PHASE_CASES = (0.0, -0.333333, 0.333333)
PINS_FUNCTIONS = ('_prepare_clip_pin', 'slice_step', 'header_audio_phase',
                  'pins_audio_phase', 'pins_trim_totals')
MASKED_FUNCTIONS = ('mask_profile', 'handover_frames', '_pin_mask_shape',
                    'masked_window_ok', 'apply_masked_pins')
FRAMES_FUNCTIONS = ('frames_to_latents', 'frame_at_latent', 'pixel_frames',
                    'step_offsets', 'steps_for_frames', 'snap_window',
                    'audio_total', 'audio_span', 'audio_overhang')
FRAMES_CONSTANTS = ('FPS', 'AUDIO_LATENT_FPS', 'FRAME_RESCALE', 'FRAMES_PER_GROUP',
                    'FRAME_BASE', 'LATENTS_PER_GROUP', 'LATENT_BASE',
                    'FRAME_PER_TOKEN', 'WINDOW_LADDER')
MASKED_CONSTANTS = ('SHARED_AV_GRID_BASE', 'SHARED_AV_GRID_STEP')


class ShapeTensor:
    """No dense data: shape, scalar/vector profile and normalized write trace.

    Slice semantics use Python's slice.indices; assignment rejects incompatible
    broadcasting instead of accepting a bogus tensor shape. Profiles have at
    most 4096 values; latent tensors never allocate data.
    """
    device = 'cpu-shape-only'
    dtype = 'float32'

    def __init__(self, shape, label='tensor', values=None, reads=()):
        self.shape = tuple(int(n) for n in shape)
        if len(self.shape) > 8 or any(n < 0 for n in self.shape):
            raise ValueError('Unsupported shape')
        self.label, self.values, self.reads = label, values, list(reads)
        self.writes = []

    def _selection(self, key):
        key = key if isinstance(key, tuple) else (key,)
        if sum(k is Ellipsis for k in key) > 1:
            raise IndexError('Multiple ellipses')
        if Ellipsis in key:
            i = key.index(Ellipsis)
            key = key[:i] + (slice(None),) * (len(self.shape) - len(key) + 1) + key[i + 1:]
        key += (slice(None),) * (len(self.shape) - len(key))
        if len(key) != len(self.shape):
            raise IndexError('Wrong index rank')
        shape, coords = [], []
        for size, index in zip(self.shape, key):
            if isinstance(index, slice):
                start, stop, step = index.indices(size)
                shape.append(len(range(start, stop, step)))
                coords.append([start, stop, step])
            elif isinstance(index, int):
                index = index + size if index < 0 else index
                if not 0 <= index < size:
                    raise IndexError('Index out of bounds')
                coords.append(index)
            else:
                raise TypeError('Only integer/slice/ellipsis indices supported')
        return tuple(shape), coords

    def __getitem__(self, key):
        shape, coords = self._selection(key)
        values = None
        if self.values is not None and len(self.shape) == 1:
            values = self.values[key] if isinstance(key, (int, slice)) else None
            if isinstance(values, (int, float)):
                values = [values]
        return ShapeTensor(shape, self.label, values,
                           self.reads + [{'label': self.label, 'slice': coords}])

    def __setitem__(self, key, value):
        shape, coords = self._selection(key)
        if isinstance(value, ShapeTensor):
            rhs = value.shape
            if len(rhs) > len(shape) or any(a != b and a != 1 for a, b in zip(rhs[::-1], shape[::-1])):
                raise ValueError(f'Assignment shape mismatch: {rhs} -> {shape}')
            record = {'source_label': value.label, 'source_shape': list(rhs),
                      'source_reads': value.reads}
            if value.values is not None:
                record['profile_values'] = list(value.values)
        elif isinstance(value, (int, float)):
            record = {'scalar': value}
        else:
            raise TypeError('Unsupported assignment')
        self.writes.append({'target_slice': coords, 'target_shape': list(shape), **record})

    def clone(self):
        return ShapeTensor(self.shape, self.label, self.values, self.reads)

    def to(self, *_args, **_kwargs):
        return self

    def view(self, *shape):
        if math.prod(shape) != math.prod(self.shape):
            raise ValueError('View changes element count')
        return ShapeTensor(shape, self.label, self.values, self.reads)

    def flatten(self):
        return self.view(math.prod(self.shape))

    def tolist(self):
        if self.values is None:
            raise ValueError('No numerical payload in a shape-only latent')
        return list(self.values)

    def item(self):
        if self.shape or self.values is None or len(self.values) != 1:
            raise ValueError('Not a scalar profile')
        return self.values[0]


class ProfileTorch:
    """Only constructors needed by mask_profile and feather=0 placement."""
    float32 = 'float32'

    @staticmethod
    def ones(shape, **_kwargs):
        return ShapeTensor(shape, 'mask-ones')

    @staticmethod
    def full(shape, fill, **_kwargs):
        if len(shape) != 1 or shape[0] > MAX_RAW_FRAMES:
            raise ValueError('Profile allocation bound')
        return ShapeTensor(shape, 'profile', [fill] * shape[0])

    @staticmethod
    def zeros(shape, **kwargs):
        return ProfileTorch.full(shape, 0.0, **kwargs)

    @staticmethod
    def tensor(values, **_kwargs):
        values = list(values)
        if len(values) > MAX_RAW_FRAMES:
            raise ValueError('Profile allocation bound')
        return ShapeTensor((len(values),), 'profile', values)


class NestedShape:
    is_nested = True

    def __init__(self, tensors):
        self.tensors = tuple(tensors)


@contextmanager
def scoped_nested_tensor():
    """Never replace installed torch; restore both module entries on all exits."""
    names = ('comfy', 'comfy.nested_tensor')
    missing = object()
    previous = {name: sys.modules.get(name, missing) for name in names}
    comfy = ModuleType('comfy')
    comfy.__path__ = []
    nested = ModuleType('comfy.nested_tensor')
    setattr(nested, 'NestedTensor', NestedShape)
    setattr(comfy, 'nested_tensor', nested)
    sys.modules.update({'comfy': comfy, 'comfy.nested_tensor': nested})
    try:
        yield
    finally:
        for name in names:
            if previous[name] is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = cast(ModuleType, previous[name])


class TraceLog:
    def __init__(self):
        self.warnings = []

    def warning(self, text, *args):
        if len(self.warnings) < 8:
            self.warnings.append(text % args)

    def info(self, *_args):
        pass

    debug = info

    def drain(self):
        result, self.warnings = self.warnings, []
        return result


def parse_pins_dependency(header):
    """Explicit double for mctx.parse_pins, not imported upstream code."""
    value = header.get('pins', [])
    if isinstance(value, str):
        if len(value) > 65536:
            raise ValueError('Recipe exceeds probe bound')
        value = json.loads(value)
    if not isinstance(value, list) or len(value) > 16 or any(not isinstance(p, dict) for p in value):
        raise ValueError('Unsupported recipe')
    return value


def extract_reference(path, functions, constants=(), globals_=None):
    """Compile only exact named definitions; top-level imports/code never run."""
    path = Path(path).resolve(strict=True)
    with path.open('rb') as stream:
        data = stream.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError('Reference source exceeds 1 MiB')
    tree = ast.parse(data, filename=str(path))
    selected, found = [], []
    for node in tree.body:
        name = None
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            if node.decorator_list:
                raise ValueError('Decorated reference functions are unsupported')
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in constants:
                name = node.targets[0].id
                allowed = (ast.Constant, ast.Tuple, ast.List, ast.BinOp, ast.UnaryOp,
                           ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                           ast.USub, ast.UAdd, ast.Load)
                if any(not isinstance(n, allowed) for n in ast.walk(node.value)):
                    raise ValueError(f'Non-arithmetic reference constant: {name}')
        if name is not None:
            found.append(name)
            selected.append(node)
    expected = set(functions) | set(constants)
    if len(found) != len(expected) or set(found) != expected:
        raise ValueError(f'Missing or duplicate reference definitions: expected {sorted(expected)}, found {found}')
    namespace = {'__name__': '__offline_reference__', **(globals_ or {})}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return SimpleNamespace(**namespace), {
        'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(),
        'size_bytes': len(data), 'functions': list(functions), 'constants': list(constants),
        'definition_lines': {n.name: [n.lineno, n.end_lineno] for n in selected if isinstance(n, ast.FunctionDef)}}


def load_reference(pins_source, masked_source, frames_source):
    log = TraceLog()
    frames, frames_meta = extract_reference(frames_source, FRAMES_FUNCTIONS, FRAMES_CONSTANTS)
    masked, masked_meta = extract_reference(masked_source, MASKED_FUNCTIONS, MASKED_CONSTANTS,
                                            {'fr': frames, 'torch': ProfileTorch, '_LOG': log})
    pins, pins_meta = extract_reference(pins_source, PINS_FUNCTIONS, globals_={
        'fr': frames, 'nodes_masked': masked, 'math': math, '_LOG': log,
        'mctx': SimpleNamespace(parse_pins=parse_pins_dependency)})
    return SimpleNamespace(frames=frames, pins=pins, masked=masked, log=log,
                           sources={'pins': pins_meta, 'masked': masked_meta, 'frames': frames_meta})


def synthetic_state(ref, raw, head=0, phase=0.0, tail=0):
    if not 5 <= raw <= MAX_RAW_FRAMES:
        raise ValueError('Raw frame count exceeds probe bound')
    steps = ref.frames.steps_for_frames(raw)
    if steps is None:
        raise ValueError('Synthetic raw count is not an exact latent cover')
    return {'fixture_kind': 'synthetic_numeric', 'meta': {
        'raw_frames': str(raw), 'pinned_head_frames': str(head),
        'pinned_tail_frames': str(tail), 'delivered_frames': str(raw - head - tail),
        'audio_phase': f'{phase:.6f}'},
        'video_shape': [1, 16, steps, 2, 3],
        'audio_shape': [1, 32, 2, ref.frames.audio_total(raw)]}


def prepare_pin(ref, state, take_from='tail', place='before', window=39,
                audio_window=0, snap_down=False, **shape):
    bundle = {'meta': state['meta'],
              'video_latent': ShapeTensor(state['video_shape'], 'source-video'),
              'audio_latent': ShapeTensor(state['audio_shape'], 'source-audio'),
              'self_id': 'synthetic-fixture' if state['fixture_kind'] == 'synthetic_numeric' else 'header-only',
              'origin': 'sampled'}
    return ref.pins._prepare_clip_pin(0, {
        'source': bundle, 'source_kind': 'clip', 'take_from': take_from,
        'place': place, 'requested_window': window, 'audio_window': audio_window,
        'handover_edge': True, 'mode': 'masked', **shape}, snap_down)


def pin_summary(pin):
    return {key: pin[key] for key in ('place', 'steps', 'covered', 'audio_steps',
                                     'overhang', 'audio_phase')} | {
        'source_start': pin['spec']['source_start'],
        'audio_start_step': pin['spec']['audio_start_step'],
        'video_reads': pin['video'].reads,
        'audio_reads': pin['audio'].reads if pin['audio'] is not None else []}


def apply_pin(ref, pin, target_raw):
    return apply_pins(ref, [pin], target_raw)


def apply_pins(ref, pins, target_raw):
    """Execute the exact mask-placement function with all boundary pins together."""
    if not pins:
        raise ValueError('At least one prepared pin is required')
    pin = pins[0]
    target = synthetic_state(ref, target_raw)
    # Real-header probes retain source channels/resolution; only time changes.
    video_shape = pin['video'].shape[:2] + (target['video_shape'][2],) + pin['video'].shape[3:]
    audio_shape = (pin['audio'].shape[:-1] if pin.get('audio') is not None
                   else tuple(target['audio_shape'][:-1])) + (target['audio_shape'][-1],)
    latent = {'samples': NestedShape((ShapeTensor(video_shape, 'target-video'),
                                      ShapeTensor(audio_shape, 'target-audio')))}
    with scoped_nested_tensor():
        result = ref.masked.apply_masked_pins(latent, pins, audio_feather_ticks=0)
    video, audio = result['samples'].tensors
    vm, am = result['noise_mask'].tensors
    return {'target_raw_frames': target_raw, 'video_writes': video.writes,
            'audio_writes': audio.writes, 'video_mask_writes': vm.writes,
            'audio_mask_writes': am.writes,
            'child_audio_phase': ref.pins.pins_audio_phase(pins, target_raw),
            'warnings': ref.log.drain()}


def probe_state(ref, state, take_from, target_raws=TARGET_CASES, **kwargs):
    place = 'before' if take_from == 'tail' else 'after'
    record = {'state': state, 'take_from': take_from, 'place': place, 'parameters': kwargs}
    try:
        pin = prepare_pin(ref, state, take_from, place, **kwargs)
    except (ValueError, RuntimeError) as exc:
        return record | {'prepare_status': 'refused', 'error': str(exc), 'warnings': ref.log.drain()}
    head, tail = ref.pins.pins_trim_totals([pin])
    record.update(prepare_status='ok', pin=pin_summary(pin), handover_head=head,
                  handover_tail=tail, warnings=ref.log.drain(), placements=[])
    for raw in target_raws:
        try:
            result = apply_pin(ref, pin, raw)
            result['status'] = 'ok'
        except (ValueError, RuntimeError) as exc:
            result = {'target_raw_frames': raw, 'status': 'refused', 'error': str(exc),
                      'warnings': ref.log.drain()}
        record['placements'].append(result)
    return record


def future_loops(ref):
    """Project from actual prepared phase/trim, then re-run the source slicer.

    No application acceptance policy is consulted. Each trajectory keeps one
    target raw length; a short delivered child may still use its held head.
    """
    rows = []
    for root_raw in TARGET_CASES:
        for child_raw in TARGET_CASES:
            state = synthetic_state(ref, root_raw)
            for generation in range(6):
                row = {'root_raw_frames': root_raw, 'child_raw_frames': child_raw,
                       'generation': generation, 'state': state}
                placement_warnings = []
                try:
                    pin = prepare_pin(ref, state)
                    placement = apply_pin(ref, pin, child_raw)
                    placement_warnings = placement['warnings']
                    head, tail = ref.pins.pins_trim_totals([pin])
                    phase = ref.pins.pins_audio_phase([pin], child_raw)
                    row.update(status='ok', pin=pin_summary(pin), handover_head=head,
                               handover_tail=tail, saved_child_phase=f'{phase:.6f}',
                               audio_writes=placement['audio_writes'])
                    state = synthetic_state(ref, child_raw, head, phase, tail)
                except (ValueError, RuntimeError) as exc:
                    row.update(status='refused', error=str(exc))
                row['warnings'] = placement_warnings + ref.log.drain()
                rows.append(row)
                if row['status'] == 'refused':
                    break
    return rows


def measured_states(work):
    """Read bounded real headers only; never payloads or saved file changes."""
    from safetensor_header import read_safetensors_header
    from h3_av_state import state_from_header

    root = Path(work).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('--work must name a directory')
    paths, scanned_dirs, scanned_files, truncated = [], 0, 0, False
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not Path(directory, d).is_symlink())
        scanned_dirs += 1
        scanned_files += len(files)
        if scanned_dirs > 512 or scanned_files > 8192:
            truncated = True
            break
        for name in sorted(files):
            if name.endswith('.mctx.safetensors') and not Path(directory, name).is_symlink():
                paths.append(Path(directory, name))
                if len(paths) >= 32:
                    truncated = True
                    break
        if truncated:
            break
    states, errors = [], []
    for path in paths:
        try:
            with path.open('rb') as stream:
                header = read_safetensors_header(stream)
            av = state_from_header(header)
            if not 5 <= av.raw_frames <= MAX_RAW_FRAMES:
                raise ValueError('Real header exceeds temporal probe bound')
            state = {'fixture_kind': 'measured_header_shapes', 'path': str(path),
                     'meta': dict(header.metadata),
                     'video_shape': list(header.tensors['video'].shape),
                     'audio_shape': list(header.tensors['audio'].shape),
                     'project_av_state': {'raw_frames': av.raw_frames, 'pinned_head': av.pinned_head,
                                          'delivered_frames': av.delivered_frames,
                                          'audio_ticks': av.audio_ticks, 'audio_phase': str(av.audio_phase)}}
            states.append(state)
        except (KeyError, ValueError, OSError) as exc:
            errors.append({'path': str(path), 'error': str(exc)})
    return states, {'root': str(root), 'candidate_headers': len(paths),
                    'scanned_directories': scanned_dirs, 'scanned_files': scanned_files,
                    'scan_truncated': truncated, 'errors': errors,
                    'payload_bytes_read': 0}


def run_probe(ref, work=None):
    cases = [probe_state(ref, synthetic_state(ref, raw, head, phase), take)
             for raw in RAW_CASES for head in (0, 35) for phase in PHASE_CASES
             for take in ('head', 'tail')]
    # Additional lengths isolate legal guide windows from illegal masked ones,
    # snap-down, split audio and held tails, without a combinatorial framework.
    extras = [probe_state(ref, synthetic_state(ref, 124), 'tail', window=w)
              for w in (1, 22, 56, 90, 141)]
    extras.append(probe_state(ref, synthetic_state(ref, 56), 'tail', window=90, snap_down=True))
    extras.append(probe_state(ref, synthetic_state(ref, 124), 'tail', audio_window=22))
    extras.append(probe_state(ref, synthetic_state(ref, 192, tail=34), 'tail'))
    for take in ('head', 'tail'):
        for ramp, edge, deep in ((17, .6, 0.), (0, 0., .3), (0, 0., 1.)):
            extras.append(probe_state(ref, synthetic_state(ref, 124), take,
                                      mask_ramp_frames=ramp, mask_ramp_edge=edge, mask_hold=deep))
    profiles = []
    for place in ('before', 'after'):
        for ramp, edge, deep in ((0, 0., 0.), (17, .6, 0.), (19, .6, 0.),
                                 (0, 0., .3), (0, 0., 1.)):
            steps = ref.frames.steps_for_frames(39)
            pin = {'covered': 39, 'place': place, 'spec': {
                'mask_ramp_frames': ramp, 'mask_ramp_edge': edge, 'mask_hold': deep,
                'handover_edge': True}}
            profiles.append({'place': place, 'ramp_frames': ramp, 'edge': edge, 'deep': deep,
                'profile': ref.masked.mask_profile(39, steps, place, ramp, edge, deep).tolist(),
                'pin_mask_shape': list(ref.masked._pin_mask_shape(pin)),
                'handover_without_decode_edge': ref.masked.handover_frames(39, place, ramp, edge, deep),
                'handover_with_decode_edge': ref.masked.handover_frames(39, place, ramp, edge, deep, decode_edge=True),
                'trim_totals': list(ref.pins.pins_trim_totals([pin]))})
    real, scan = [], None
    if work is not None:
        states, scan = measured_states(work)
        real = [probe_state(ref, state, take) for state in states for take in ('head', 'tail')]
    loops = future_loops(ref)
    all_cases = cases + extras + real
    placements = [p for c in all_cases for p in c.get('placements', [])]
    frame_arithmetic = [
        {'raw_frames': raw, 'frames_to_latents': ref.frames.frames_to_latents(raw),
         'steps_for_frames': ref.frames.steps_for_frames(raw),
         'audio_total': ref.frames.audio_total(raw),
         'audio_overhang': ref.frames.audio_overhang(ref.frames.audio_total(raw), raw)}
        for raw in RAW_CASES]
    slice_arithmetic = [
        {'frame': frame, 'phase': phase, 'slice_step': ref.pins.slice_step(frame, phase)}
        for frame in (0, 17, 35, 85, 119, 153) for phase in PHASE_CASES]
    legacy_recipe = {'source_kind': 'clip', 'source_start': 85, 'source_frames': 39}
    headers = [None, {'audio_phase': '-0.333333'},
               {'raw_frames': '124', 'pins': json.dumps([dict(legacy_recipe, place='before')])},
               {'raw_frames': '124', 'pins': json.dumps([dict(legacy_recipe, place='after')])}]
    header_phases = [{'header': header, 'audio_phase': ref.pins.header_audio_phase(header)}
                     for header in headers]
    return {'schema': 'h3-native-boundary-source-probe-v1', 'sources': ref.sources,
        'evidence_kind': 'numeric_control_flow_with_shape_only_doubles',
        'limits': ['No tensor payload, GPU, sampler, VAE or rendered-quality proof.',
                   'Synthetic numeric fixtures are not measured jobs or API results.',
                   'Only explicitly named source definitions/constants execute; sources must be trusted.',
                   'mctx.parse_pins is a bounded JSON-recipe dependency double, not extracted source.',
                   'Profile floats use Python precision, not torch float32 rounding.',
                   'Audio feather is fixed at zero; feather math is not exercised.',
                   'Future fixtures round inferred child phase to six decimals; the saver is not executed.',
                   'apply_masked_pins is exercised directly, not the outer H3MCtxApplyPins validation.'],
        'configuration': {'raw_frames': list(RAW_CASES), 'target_raw_frames': list(TARGET_CASES),
                          'phases': list(PHASE_CASES), 'pinned_heads': [0, 35],
                          'future_max_generations': 6, 'max_real_headers': 32},
        'counts': {'synthetic_cases': len(cases), 'extra_cases': len(extras), 'real_cases': len(real),
                   'prepare_ok': sum(c['prepare_status'] == 'ok' for c in all_cases),
                   'prepare_refused': sum(c['prepare_status'] == 'refused' for c in all_cases),
                   'placements': len(placements),
                   'placement_ok': sum(p['status'] == 'ok' for p in placements),
                   'placement_refused': sum(p['status'] == 'refused' for p in placements),
                   'mask_profiles': len(profiles), 'frame_arithmetic': len(frame_arithmetic),
                   'slice_arithmetic': len(slice_arithmetic), 'header_phases': len(header_phases),
                   'future_steps': len(loops),
                   'future_refused': sum(row['status'] == 'refused' for row in loops)},
        'synthetic_cases': cases, 'extra_cases': extras, 'mask_profiles': profiles,
        'frame_arithmetic': frame_arithmetic, 'slice_arithmetic': slice_arithmetic,
        'header_phases': header_phases,
        'future_loops': loops, 'real_cases': real, 'work_scan': scan}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pins-source', required=True, type=Path)
    parser.add_argument('--masked-source', required=True, type=Path)
    parser.add_argument('--frames-source', required=True, type=Path)
    parser.add_argument('--work', type=Path, help='Read at most 32 real mctx headers; no payload reads')
    args = parser.parse_args(argv)
    try:
        report = run_probe(load_reference(args.pins_source, args.masked_source, args.frames_source), args.work)
    except (OSError, ValueError, SyntaxError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
