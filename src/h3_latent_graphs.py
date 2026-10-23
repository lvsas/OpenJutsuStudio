"""Compile a full-latent continuity graph from the adopted Calliope template.

The template (workflow 12920) parameterises everything through nested bundles.
Rather than editing values in place and hoping they are read, every binding below
is applied to a fresh copy and then read back: a binding that silently misses its
target is the exact failure mode this module exists to prevent.

References are not routed through the template's ``h3_refs`` bundle: one
``LoadImage`` per reference feeds ``ref_images.ref_image_N`` directly, which is how
the Swap already handles an arbitrary number of them.

Forward, prepend and bridge describe compile-time native pin placement, not
executed/render-validated capabilities. Prepend anchors the parent's head after
the generated segment; it never reverses playback. The controller must separately
attest parent identity/geometry/models and precheck saved A/V temporal capacity.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

TEMPLATE = Path(__file__).resolve().parents[1] / 'workflows/h3-continuity-latent.api.json'
MODES = ('forward', 'prepend', 'bridge')
_HEX32 = re.compile(r'[0-9a-f]{32}\Z')
_ASSET = re.compile(r'[A-Za-z0-9_.:-]{1,256}\Z')

UNET_NODE = '725'
CLIP_NODE = '752:747'
VIDEO_VAE_NODE = '752:748'
AUDIO_VAE_NODE = '752:798'
PROMPT_NODE = '761:763'
INPUT_BUNDLE = '761:1381'
GENERATE_NODE = '797'
SAVE_FOLDER_NODE = '761:1217'
SAVER_NODE = '1216'
PARENT_NODE = '2010'
SECOND_PARENT_NODE = '2011'
PIN_NODE = '2020'
SECOND_PIN_NODE = '2021'
APPLY_NODE = '1228'
SEED_NODE = '2004'
DURATION_NODE = '2001'
FAMILY_NODE = 'native_family'
HANDLE_NODE = 'native_clip_handle'
SWITCH_CLASS = 'ComfySwitchNode'
BOOLEAN_LITERAL = 'PrimitiveBoolean'
STYLE_LORA_CLASS = 'LoraLoaderModelOnly'
PREFLIGHT_CLIP = 'preflight/not-a-real-clip.mp4'


def _is_ref(value):
    return (isinstance(value, list) and len(value) == 2
            and isinstance(value[0], str) and type(value[1]) is int)


def _asset(value):
    info = value.get('info') if isinstance(value, dict) else None
    identifier = info.get('id') if isinstance(info, dict) else None
    if (not isinstance(value, dict) or value.get('__type') != 'core/ASSET'
            or not isinstance(identifier, str) or not _ASSET.fullmatch(identifier)):
        raise ValueError('Each reference must be a committed SDK asset')
    return {'__type': 'core/ASSET', 'info': {'id': identifier}}


def _weight(models, name):
    value = getattr(models, name, None)
    filename = getattr(value, 'filename', None)
    if not isinstance(filename, str) or not filename:
        raise ValueError(f'A complete model profile is required; {name} is missing')
    return filename


def _parent_clip(value):
    # Validate spelling only: existence/restaging and identity are caller attestations.
    # Preserve spaces/parentheses that the server may add during deduplication.
    if (not isinstance(value, str) or not value or value != value.strip()
            or not value.endswith('.mp4') or value.startswith('/')
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or ':' in value or '\\' in value
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise ValueError('A restaged output-relative parent clip handle is required')


def _parents(mode, parent_clip, second_parent_clip):
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError('Mode must be forward, prepend or bridge')
    _parent_clip(parent_clip)
    if mode == 'bridge':
        _parent_clip(second_parent_clip)
        if parent_clip == second_parent_clip:
            raise ValueError('Bridge requires distinct restaged parent clip handles')
    elif second_parent_clip is not None:
        raise ValueError('A second parent clip handle is only legal for bridge')


def build_latent_continuity(*, references, prompt, width, height, raw_frames, seed,
                            models, parent_clip, operation_id, publish_family=False,
                            mode='forward', second_parent_clip=None):
    """Compile bounded pin topology only; no temporal attestation or GPU execution.

    Forward uses tail(parent)/before; prepend uses head(parent)/after; bridge
    chains tail(parent A)/before and head(parent B)/after. Supplied handles must
    already be restaged and independently attested by the calling controller.
    """
    _parents(mode, parent_clip, second_parent_clip)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('An effective prompt is required')
    if not isinstance(references, (list, tuple)) or not references:
        raise ValueError('At least one character reference is required')
    if not isinstance(operation_id, str) or not _HEX32.fullmatch(operation_id):
        raise ValueError('A server-generated 32-hex operation identifier is required')
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError('A positive integer geometry is required')
    if (type(raw_frames) is not int or not 5 <= raw_frames <= 3600
            or (raw_frames - 5) % 17):
        raise ValueError('Native frames must be on the 17k+5 grid in [5, 3600]')
    if type(seed) is not int or not 0 <= seed <= 2**64 - 1:
        raise ValueError('The seed must be an integer in the native range')
    if type(publish_family) is not bool:
        raise ValueError('Family publication must be an explicit boolean')

    graph = copy.deepcopy(json.loads(TEMPLATE.read_text()))
    # Only the explicit parent pair adaptation below may change native topology.
    if not isinstance(graph, dict) or any(
            not isinstance(node, dict) or not isinstance(node.get('inputs'), dict)
            for node in graph.values()):
        raise ValueError('Template must be an API graph with node input mappings')

    def bind(node, field, value):
        if node not in graph or field not in graph[node]['inputs']:
            raise ValueError(f'Template binding {node}.{field} no longer exists')
        graph[node]['inputs'][field] = value
        return value

    # Weights. The template ships a pruned ref2va build; the caller decides.
    bind(UNET_NODE, 'unet_name', _weight(models, 'unet'))
    bind(CLIP_NODE, 'clip_name', _weight(models, 'clip'))
    bind(VIDEO_VAE_NODE, 'vae_name', _weight(models, 'video_vae'))
    bind(AUDIO_VAE_NODE, 'vae_name', _weight(models, 'audio_vae'))

    bind(PROMPT_NODE, 'value', prompt)
    bind(SEED_NODE, 'value', seed)
    # The template derives length from a duration in seconds through a 17k+5 grid
    # expression; a value that rounds to another frame count is refused below.
    bind(DURATION_NODE, 'value', raw_frames / 24)
    bind(PARENT_NODE, 'clip', parent_clip)
    if mode == 'prepend':
        bind(PIN_NODE, 'take_from', 'head')
        bind(PIN_NODE, 'place', 'after')
    elif mode == 'bridge':
        if SECOND_PARENT_NODE in graph or SECOND_PIN_NODE in graph:
            raise ValueError('Template already contains the reserved second parent pair')
        if PIN_NODE not in graph:
            raise ValueError('Template parent pin no longer exists')
        graph[SECOND_PARENT_NODE] = copy.deepcopy(graph[PARENT_NODE])
        graph[SECOND_PIN_NODE] = copy.deepcopy(graph[PIN_NODE])
        bind(SECOND_PARENT_NODE, 'clip', second_parent_clip)
        bind(SECOND_PIN_NODE, 'mctx', [SECOND_PARENT_NODE, 3])
        bind(SECOND_PIN_NODE, 'take_from', 'head')
        bind(SECOND_PIN_NODE, 'place', 'after')
        graph[SECOND_PIN_NODE]['inputs']['pin_specs'] = [PIN_NODE, 0]
        bind(APPLY_NODE, 'pin_specs', [SECOND_PIN_NODE, 0])
    bind(SAVE_FOLDER_NODE, 'value', f'OpenGenjutsu/continuity/takes/{operation_id}')
    bind(SAVER_NODE, 'filename_prefix', 'take')

    # Geometry: the template would derive it from an aspect ratio; a continuation
    # keeps the parent's exact frame size instead.
    graph['bound_width'] = {'class_type': 'INTConstant', 'inputs': {'value': width}}
    graph['bound_height'] = {'class_type': 'INTConstant', 'inputs': {'value': height}}
    bind(INPUT_BUNDLE, 'in_2', ['bound_width', 0])
    bind(INPUT_BUNDLE, 'in_3', ['bound_height', 0])

    # References: one loader per reference, ordered, feeding ref_image_N directly.
    for position, reference in enumerate(references):
        node = f'ref_image_{position}'
        graph[node] = {'class_type': 'LoadImage', 'inputs': {'image': _asset(reference)}}
        graph[GENERATE_NODE]['inputs'][f'ref_images.ref_image_{position}'] = [node, 0]

    # The template's saver exposes the clip path as its first output; our installed
    # pack turns it into a published family plus a handle the app can read back.
    if publish_family:
        graph[FAMILY_NODE] = {'class_type': 'OpenGenjutsuH3PublishClip',
                              'inputs': {'clip': [SAVER_NODE, 0]}}
        graph[HANDLE_NODE] = {'class_type': 'SaveText', 'inputs': {
            'text': [FAMILY_NODE, 0], 'format': 'txt',
            'filename_prefix': f'OpenGenjutsu/continuity/takes/{operation_id}/handle'}}

    _verify(graph, width, height, raw_frames, seed, prompt, references, operation_id,
            mode=mode, parent_clip=parent_clip, second_parent_clip=second_parent_clip)
    return graph


def _verify_state_flow(graph, mode, parent_clip, second_parent_clip):
    """Guard effective native pins and the adopted generation/refine wiring.

    These are structural contracts, not an implementation of native A/V slicing,
    mask placement, trim math, or a proof of a parent's temporal compatibility.
    """
    def check(node, class_type, fields, *, exact=False):
        actual = graph.get(node, {})
        if actual.get('class_type') != class_type:
            raise ValueError(f'Template node {node} must be {class_type}')
        inputs = actual.get('inputs', {})
        if exact and inputs != fields:
            raise ValueError(f'Effective native inputs drifted at {node}')
        for field, expected in fields.items():
            if field not in inputs or inputs[field] != expected:
                raise ValueError(f'Effective state flow drifted at {node}.{field}')

    pairs = [(PARENT_NODE, PIN_NODE, parent_clip,
              'head' if mode == 'prepend' else 'tail',
              'after' if mode == 'prepend' else 'before')]
    if mode == 'bridge':
        pairs.append((SECOND_PARENT_NODE, SECOND_PIN_NODE, second_parent_clip, 'head', 'after'))
    elif SECOND_PARENT_NODE in graph or SECOND_PIN_NODE in graph:
        raise ValueError('A non-bridge graph contains a second parent pair')
    for loader, pin, clip, take_from, place in pairs:
        check(loader, 'H3LoadVideoWithMCtx',
              {'clip': clip, 'create_pins': 'none', 'pin_window': '39'}, exact=True)
        inputs = {'audio_window': 0, 'mask_hold': 0.0, 'mask_ramp_edge': 0.0,
                  'mask_ramp_frames': 0, 'mctx': [loader, 3], 'mode': 'masked',
                  'place': place, 'place_at_frame': 0, 'take_from': take_from,
                  'take_from_frame': 0, 'window': '39'}
        if pin == SECOND_PIN_NODE:
            inputs['pin_specs'] = [PIN_NODE, 0]
        check(pin, 'H3MCtxPinSpec', inputs, exact=True)
    for class_type, expected in (
            ('H3LoadVideoWithMCtx', {pair[0] for pair in pairs}),
            ('H3MCtxPinSpec', {pair[1] for pair in pairs}),
            ('H3MCtxApplyPins', {APPLY_NODE})):
        if {node for node, value in graph.items() if value.get('class_type') == class_type} != expected:
            raise ValueError(f'Unexpected native continuity nodes: {class_type}')

    # Pass 1's guider, sampler, saver and both decoders share the same pinned
    # conditioning/latent/sampled slot; the parent loader is never decoded here.
    check(APPLY_NODE, 'H3MCtxApplyPins', {
        'conditioning': [GENERATE_NODE, 0], 'latent': [GENERATE_NODE, 1],
        'pin_specs': [SECOND_PIN_NODE if mode == 'bridge' else PIN_NODE, 0],
        'snap_window_down_to_available': True, 'audio_denoise': 0,
        'freeze_audio': False, 'masked_audio_feather': 8,
        'audio_vae': ['1376', 2], 'video_vae': ['1376', 1]})
    check('1488:1483', 'BasicGuider', {'conditioning': [APPLY_NODE, 0], 'model': ['3001', 0]})
    check('1488:1486', 'SamplerCustomAdvanced', {
        'guider': ['1488:1483', 0], 'latent_image': [APPLY_NODE, 1]})
    check('3001', 'PixaromaH3AudioSync', {'latent': [APPLY_NODE, 1]})
    check(SAVER_NODE, 'H3TrimAndSaveVideoWithMCtx', {
        'conditioning': [APPLY_NODE, 0], 'pins': [APPLY_NODE, 2],
        'samples': ['1488:1486', 1], 'save_conditioning': True,
        'images': ['751:632', 0], 'audio': ['751:633', 0], 'filename_prefix': 'take'})
    check('751:632', 'VAEDecode', {'samples': ['1488:1486', 1]})
    check('751:633', 'VAEDecodeAudio', {'samples': ['1488:1486', 1]})

    # Preserve the separate sequence -> joint state -> AV upscale -> refine path.
    # It is not the generation saver's sampled output, nor an extra pin engine.
    check('1349', 'H3JointLatent', {'sequence': ['1448:1279', 0]})
    check('1448:1279', 'MuteGate (obvpm)', {'input': ['1448:1453', 0]})
    check('1448:1453', 'Unbundle (obvpm)',
          {'in': ['1449', 0], 'names': 'sequence\nupscaling'})
    check('1449', 'Bundle (obvpm)',
          {'in_1': ['2005', 1], 'in_2': ['2003', 0], 'in_3': ['2002', 0],
           'names': 'length\nsequence\nupscaling'})
    check('1350', 'LTXVSeparateAVLatent', {'av_latent': ['1349', 0]})
    check('1351', 'MinimaxH3LatentUpscaler3D', {'latent': ['1350', 0]})
    check('1352', 'LTXVConcatAVLatent',
          {'audio_latent': ['1350', 1], 'video_latent': ['1351', 0]})
    check('1365', 'CleanVRAM (obvpm)', {'anything': ['1352', 0]})
    check('1363', 'H3JointAudioMask', {'latent': ['1365', 0], 'audio_denoise': 0})
    check('1362', 'H3JointConditioning', {'layout': ['1349', 1]})
    check('1359:1311', 'BasicGuider', {'conditioning': ['1362', 0]})
    check('1359:1313', 'SamplerCustomAdvanced',
          {'latent_image': ['1363', 0], 'guider': ['1359:1311', 0]})
    check('1366', 'CleanVRAM (obvpm)', {'anything': ['1359:1313', 1]})
    check('1434', 'H3JointRender', {'samples': ['1366', 0], 'conditioning': ['1362', 0],
                                  'layout': ['1349', 1], 'source_audio': ['1350', 1]})
    # Confirm the length expression and its effective generation input, without
    # duplicating the native engine's temporal calculations in this compiler.
    check('2005', 'ComfyMathExpression', {
        'values.a': [DURATION_NODE, 0],
        'expression': 'max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17'})
    check('1473:1278', 'MuteGate (obvpm)', {'input': ['1473:1506', 0]})
    check('1473:1506', 'Unbundle (obvpm)',
          {'in': ['1449', 0], 'names': 'length\nupscaling'})
    check(GENERATE_NODE, 'MiniMaxH3ReferenceToVideo', {'length': ['1473:1278', 0]})


def _verify(graph, width, height, raw_frames, seed, prompt, references, operation_id,
            *, mode, parent_clip, second_parent_clip=None):
    """Read every binding back; a silent miss must never reach the target."""
    _parents(mode, parent_clip, second_parent_clip)
    _verify_state_flow(graph, mode, parent_clip, second_parent_clip)
    try:
        json.dumps(graph, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError('Compiled graph must be finite JSON') from exc
    checks = [
        (PROMPT_NODE, 'value', prompt),
        (SEED_NODE, 'value', seed),
        (SAVE_FOLDER_NODE, 'value', f'OpenGenjutsu/continuity/takes/{operation_id}'),
        (INPUT_BUNDLE, 'in_2', ['bound_width', 0]),
        (INPUT_BUNDLE, 'in_3', ['bound_height', 0]),
        ('bound_width', 'value', width),
        ('bound_height', 'value', height),
    ]
    for node, field, expected in checks:
        actual = graph.get(node, {}).get('inputs', {}).get(field)
        if actual != expected:
            raise ValueError(f'Binding {node}.{field} was not applied')
    for position in range(len(references)):
        slot = f'ref_images.ref_image_{position}'
        if graph[GENERATE_NODE]['inputs'].get(slot) != [f'ref_image_{position}', 0]:
            raise ValueError(f'Reference slot {slot} was not bound')
        if graph.get(f'ref_image_{position}', {}).get('inputs', {}).get('image') != _asset(references[position]):
            raise ValueError(f'Reference asset {position} was not bound')
    seconds = graph[DURATION_NODE]['inputs']['value']
    if abs(seconds * 24 - raw_frames) > 1e-9:
        raise ValueError('The duration binding would not produce the requested frames')
    # A dormant dependency is what once turned a rejected prompt into a "success"
    # with no outputs: nothing compiled may be unreachable or gated by a literal.
    referenced = {reference[0] for node in graph.values() if isinstance(node, dict)
                  for reference in node.get('inputs', {}).values() if _is_ref(reference)}
    for node_id, node in graph.items():
        for field, value in node.get('inputs', {}).items():
            if _is_ref(value) and (value[0] not in graph or value[1] < 0):
                raise ValueError(f'Dangling or negative link {node_id}.{field}')
        if node.get('class_type') == STYLE_LORA_CLASS and node_id not in referenced:
            raise ValueError(f'Style LoRA {node_id} is compiled but nothing consumes it')
        if node.get('class_type') == SWITCH_CLASS and _is_ref(node['inputs'].get('switch')):
            if graph.get(node['inputs']['switch'][0], {}).get('class_type') == BOOLEAN_LITERAL:
                raise ValueError(f'Switch {node_id} still selects on a literal boolean')
