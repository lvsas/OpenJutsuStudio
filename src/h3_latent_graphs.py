"""Compile a full-latent continuity graph from the adopted Calliope template.

The template (workflow 12920) parameterises everything through nested bundles.
Rather than editing values in place and hoping they are read, every binding below
is applied to a fresh copy and then read back: a binding that silently misses its
target is the exact failure mode this module exists to prevent.

References are not routed through the template's ``h3_refs`` bundle: one
``LoadImage`` per reference feeds ``ref_images.ref_image_N`` directly, which is how
the Swap already handles an arbitrary number of them.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import re

TEMPLATE = Path(__file__).resolve().parents[1] / 'workflows/h3-continuity-latent.api.json'
MODES = ('forward', 'reverse', 'bridge')
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


def build_latent_continuity(*, references, prompt, width, height, raw_frames, seed,
                            models, parent_clip, operation_id, publish_family=False):
    """Return the compiled graph for one continuation."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('An effective prompt is required')
    if not isinstance(references, (list, tuple)) or not references:
        raise ValueError('At least one character reference is required')
    if not isinstance(operation_id, str) or not _HEX32.fullmatch(operation_id):
        raise ValueError('A server-generated 32-hex operation identifier is required')
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError('A positive integer geometry is required')
    if type(raw_frames) is not int or raw_frames < 5:
        raise ValueError('A positive native frame count is required')
    if type(seed) is not int or not 0 <= seed <= 2**64 - 1:
        raise ValueError('The seed must be an integer in the native range')
    if not isinstance(parent_clip, str) or not parent_clip:
        raise ValueError('A restaged parent clip handle is required')
    if type(publish_family) is not bool:
        raise ValueError('Family publication must be an explicit boolean')

    graph = copy.deepcopy(json.loads(TEMPLATE.read_text()))
    # The shipped template is already clean; never silently rewrite its topology.

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

    _verify(graph, width, height, raw_frames, seed, prompt, references, operation_id)
    return graph


def _verify(graph, width, height, raw_frames, seed, prompt, references, operation_id):
    """Read every binding back; a silent miss must never reach the target."""
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
    seconds = graph[DURATION_NODE]['inputs']['value']
    if abs(seconds * 24 - raw_frames) > 1e-9:
        raise ValueError('The duration binding would not produce the requested frames')
    # A dormant dependency is what once turned a rejected prompt into a "success"
    # with no outputs: nothing compiled may be unreachable or gated by a literal.
    referenced = {reference[0] for node in graph.values() if isinstance(node, dict)
                  for reference in node.get('inputs', {}).values() if _is_ref(reference)}
    for node_id, node in graph.items():
        if node.get('class_type') == STYLE_LORA_CLASS and node_id not in referenced:
            raise ValueError(f'Style LoRA {node_id} is compiled but nothing consumes it')
        if node.get('class_type') == SWITCH_CLASS and _is_ref(node['inputs'].get('switch')):
            if graph.get(node['inputs']['switch'][0], {}).get('class_type') == BOOLEAN_LITERAL:
                raise ValueError(f'Switch {node_id} still selects on a literal boolean')
