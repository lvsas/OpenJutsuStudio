"""Compile an additional native H3 capture without changing the proven Swap.

Uses the final HR AV state and its actual conditioning, not the first pass or a
reconstructed prompt. The stock saver owns MP4/MCTX/COND identity. It captures
all raw frames: the original displayed Swap may be shorter after padding removal
and uses source audio, whereas native audio is decoded from the captured AV.
Neither file nor soundtrack is silently asserted identical to the other.

Pure graph adapter: no disk/network/model access, submission or publication.
Weight hashes are explicit caller attestations, NOT measured here. Compilation
cannot approve native forward compatibility, especially across LoRA profiles.
"""
from __future__ import annotations

from collections.abc import Mapping
import copy
from dataclasses import asdict, dataclass
import hashlib
import json
import re

from h3_graphs import H3Models, REFERENCE_NODE
from h3_recipe import validate_recipe
from h3_continuity_graphs import Weight

SAVE_NODE = 'native_swap_save'
HANDLE_NODE = 'native_swap_clip_handle'
AUDIO_NODE = 'native_swap_audio'
_VERSION = 'opengenjutsu.h3-swap-capture.v1'
NATIVE_ARTIFACT_RELATION = 'native-raw-family-and-distinct-finished-swap'
_HEX32 = re.compile(r'[0-9a-f]{32}\Z')
_HEX64 = re.compile(r'[0-9a-f]{64}\Z')
_ASSET_ID = re.compile(r'[A-Za-z0-9_.:-]{1,256}\Z')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class SwapNativeCapture:
    canonical_json: str

    @property
    def digest(self):
        return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    def as_dict(self):
        return json.loads(self.canonical_json)

    @property
    def graph(self):
        return self.as_dict()['graph']


def _asset(value):
    info = value.get('info') if isinstance(value, dict) else None
    identifier = info.get('id') if isinstance(info, dict) else None
    if (not isinstance(value, dict) or value.get('__type') != 'core/ASSET'
            or not isinstance(identifier, str) or not _ASSET_ID.fullmatch(identifier)):
        raise ValueError('Native Swap requires committed SDK asset IDs')
    return identifier


def native_inventory_graph(recipe, *, operation_id, weights=None):
    """Compile the exact capture shape with sentinel assets; never submit these IDs."""
    recipe = validate_recipe(recipe)
    graph = copy.deepcopy(recipe['graph_template'])
    asset = lambda name: {'__type': 'core/ASSET', 'info': {'id': 'inventory-' + name}}
    graph['155']['inputs']['video'] = asset('source')
    for index in range(recipe['reference_count']):
        graph[str(REFERENCE_NODE + index)]['inputs']['image'] = asset(f'reference-{index}')
    graph['156']['inputs']['filename_prefix'] = f'OpenGenjutsu/h3-{operation_id}'
    profile = ({role: Weight(name) for role, name in recipe['model_files'].items()}
               if weights is None else weights)
    return build_swap_native_capture(recipe, graph, operation_id=operation_id,
                                     weights=profile, publish_family=True).graph


def build_swap_native_capture(recipe, graph, *, operation_id, weights, publish_family=False):
    """Attach a native root capture to the exact current frozen Swap graph.

    ``graph`` is the actual SDK-bound Swap graph; only its uploaded assets and
    server-owned filename prefix may differ from the independently rebuilt
    recipe. A historical capsule is not automatically executable configuration.
    This returns compiled evidence, never a claim of successful native capture.
    """
    if type(publish_family) is not bool:
        raise ValueError('Native family publication must be an explicit boolean')
    if not isinstance(operation_id, str) or not _HEX32.fullmatch(operation_id):
        raise ValueError('Native Swap requires a server-generated 32-hex ID')
    try:
        recipe = validate_recipe(recipe)
        if (recipe['source_frames_24fps'] is None
                or type(recipe.get('source_audio')) is not bool):
            raise ValueError('Native Swap requires measured source frames and audio')
        expected = copy.deepcopy(recipe['graph_template'])
        actual = copy.deepcopy(graph)
        source = _asset(actual['155']['inputs']['video'])
        refs = [_asset(actual[str(REFERENCE_NODE + i)]['inputs']['image'])
                for i in range(recipe['reference_count'])]
        expected['155']['inputs']['video'] = copy.deepcopy(actual['155']['inputs']['video'])
        for i in range(recipe['reference_count']):
            key = str(REFERENCE_NODE + i)
            expected[key]['inputs']['image'] = copy.deepcopy(actual[key]['inputs']['image'])
        expected['156']['inputs']['filename_prefix'] = f'OpenGenjutsu/h3-{operation_id}'
        if _canonical(expected) != _canonical(actual):
            raise ValueError('SDK-bound Swap graph differs outside its allowed bindings')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Incomplete native Swap source contract') from exc

    files = recipe['model_files']
    if not isinstance(weights, Mapping) or set(weights) != set(asdict(H3Models())):
        raise ValueError('All effective Swap weight roles must be attested')
    captured_weights = {}
    measured = True
    for role, filename in files.items():
        weight = weights[role]
        if (not isinstance(weight, Weight) or weight.filename != filename
                or (weight.sha256 is not None and (not isinstance(weight.sha256, str)
                                                  or not _HEX64.fullmatch(weight.sha256)))):
            raise ValueError('Swap weight identity differs from its effective recipe')
        captured_weights[role] = asdict(weight)
        measured = measured and weight.sha256 is not None

    raw, visible = recipe['inference_frames'], recipe['source_frames_24fps']
    record = {
        'version': _VERSION, 'operation_id': operation_id,
        'swap_recipe_digest': _digest(recipe), 'source_graph_digest': _digest(actual),
        'source_asset': source, 'references': refs,
        'geometry': {'width': recipe['output_width'], 'height': recipe['output_height'],
                     'fps': 24, 'raw_frames': raw, 'display_frames': visible,
                     'padding_frames': raw - visible},
        'endpoint': ('raw-equals-visible' if raw == visible
                     else 'padded-endpoint-needs-window-policy'),
        'audio': {'native': 'decoded-final-sampler-av',
                  'display': 'preserved-source' if recipe['source_audio'] else 'silent'},
        'weights': captured_weights,
        'loras': [{'role': 'turbo_lora', 'strength_model': 0.9},
                  {'role': 'swap_lora', 'strength_model': 1.0}],
        'sampler_output': ['170', 1], 'conditioning': ['136', 0],
        'seed': recipe['seed'], 'steps': recipe['steps'], 'split_step': recipe['split_step'],
        'runtime_verified': False, 'forward_verified': False,
        'artifact_relation': NATIVE_ARTIFACT_RELATION,
        # Never claim a measured identity the caller did not actually measure.
        'weight_verification': ('measured-on-owning-machine' if measured
                                else 'filename-only; bytes not measured'),
        'family_node': 'native_swap_family' if publish_family else None,
    }
    native = {
        'native_swap_av': {'class_type': 'LTXVSeparateAVLatent',
                           'inputs': {'av_latent': ['170', 1]}},
        AUDIO_NODE: {'class_type': 'VAEDecodeAudio',
                     'inputs': {'samples': ['native_swap_av', 1], 'vae': ['120', 0]}},
        SAVE_NODE: {'class_type': 'H3TrimAndSaveVideoWithMCtx', 'inputs': {
            'samples': ['170', 1], 'images': ['122', 0],
            'audio': [AUDIO_NODE, 0], 'conditioning': ['136', 0],
            'save_conditioning': True, 'base_folder': f'OpenGenjutsu/continuity/swaps/{operation_id}',
            'filename_prefix': 'take', 'crf': 19, 'metadata': _canonical(record)}},
        HANDLE_NODE: {'class_type': 'SaveText', 'inputs': {
            'text': [SAVE_NODE, 0], 'format': 'txt',
            'filename_prefix': f'OpenGenjutsu/continuity/handles/{operation_id}/swap'}},
    }
    # Exact reconstruction above makes collisions impossible; preserve every
    # original node, including its soundtrack, upscaler and visible MP4 output.
    if publish_family:
        native['native_swap_family'] = {
            'class_type': 'OpenGenjutsuH3PublishClip', 'inputs': {'clip': [SAVE_NODE, 0]}}
        # The stock saver returns an absolute path. The confined publisher
        # validates it and returns the exact output-relative loader literal.
        native[HANDLE_NODE]['inputs']['text'] = ['native_swap_family', 0]
    actual.update(native)
    return SwapNativeCapture(_canonical({**record, 'graph': actual}))
