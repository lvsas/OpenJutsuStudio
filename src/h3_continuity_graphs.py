"""Pinned native H3 generative-take graphs, independent of Swap and the app.

The finite public fixture specializes an inspected production generation branch;
its provenance records every deliberate topology/value adaptation. No submission,
file discovery, model loading or implicit replay of historical capsules occurs.
Only one committed character reference is supported in this initial adapter.

Callers supply *verified output-relative native loader literals* and measured
parent geometry/model identities, not SDK asset IDs or guessed sidecar stems.
Model hashes and parent capsule digests are caller-attested provenance, not disk
verification performed here. Historical capsule v1 is NOT executable config.

A native saver returns a clip STRING, not SDK family assets. SaveText captures that
actual STRING; a separate integrity-checked CPU publisher must publish video,
MCTX and COND. Raw frame count is never a prediction of delivered duration.
"""
from __future__ import annotations

from comfy_schema import autogrow_member_spec
from h3_latent_graphs import _asset, _bind_source_audio
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re

TEMPLATE = Path(__file__).resolve().parents[1] / 'workflows/h3-native-take.api.json'
TEMPLATE_DIGEST = '818901db5d30eb65ad9ea5abc8af3bc9d515c87e7818141a38cfa7b4e415a972'
# Opaque historical evidence identity, computed by its original permissive JSON
# serializer. It contains NaN at unused 1349.is_changed[0], never replayed here.
SOURCE_GRAPH_DIGEST = 'd80a561580babfd9684762cc05e33b014ab2727843336084f4999d2e8311bbe4'
RECIPE_VERSION = 'opengenjutsu.native-h3-continuity.v1'
HANDLE_NODE = 'native_take_clip_handle'
PIN_WINDOW = 39
_HEX32 = re.compile(r'[0-9a-f]{32}\Z')
_HEX64 = re.compile(r'[0-9a-f]{64}\Z')
_ASSET_ID = re.compile(r'[A-Za-z0-9_.:-]{1,256}\Z')
# A literal may come from a verified native source or the CPU restager. Do not
# restrict it to a guessed prefix/stem: preserve the service-returned spelling.
_PARENT_CLIP = re.compile(r'[^\x00\r\n:]{1,512}\.mp4\Z')


@dataclass(frozen=True)
class Weight:
    filename: str
    # The server resolves identity by filename. A byte hash is recorded only when
    # it was actually measured on a machine that owns the files; on a hosted
    # target nobody can hash 40 GB, so it is optional and never invented.
    sha256: str | None = None


@dataclass(frozen=True)
class H3ContinuityModels:
    unet: Weight
    clip: Weight
    video_vae: Weight
    audio_vae: Weight


@dataclass(frozen=True)
class NativeH3Parent:
    """Explicit service attestation after native family integrity checks/restaging.

    delivered_frames is a measured probe, not raw_frames minus a fixed overlap.
    capsule_digest identifies lineage only and cannot authorize capsule replay.
    """
    take_id: str
    clip: str
    width: int
    height: int
    delivered_frames: int
    fps: int
    models: H3ContinuityModels
    capsule_digest: str


@dataclass(frozen=True)
class ContinuityRecipe:
    """Immutable exact graph/controls snapshot; mutable accessors return copies."""
    canonical_json: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    @property
    def graph(self) -> dict:
        return self.as_dict()['graph']

    def as_dict(self) -> dict:
        return _loads(self.canonical_json)


def _reject_constant(value):
    raise ValueError(f'Non-finite JSON constant {value} is not replayable')


def _loads(value):
    return json.loads(value, parse_constant=_reject_constant)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def canonical_digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _load_template():
    try:
        graph = _loads(TEMPLATE.read_text())
        digest = canonical_digest(graph)
    except (ValueError, TypeError) as exc:
        raise ValueError('Continuity template digest or finite JSON validation failed') from exc
    if digest != TEMPLATE_DIGEST:
        raise ValueError('Continuity template digest mismatch')
    return graph


def _integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be an integer in [{low}, {high}]')


def _geometry(width, height, raw_frames):
    for label, value in (('width', width), ('height', height)):
        _integer(value, label, 32, 16384)
        if value % 32:
            raise ValueError(f'{label} must be aligned to 32')
    _integer(raw_frames, 'raw_frames', 5, 3600)
    if (raw_frames - 5) % 17:
        raise ValueError('raw_frames must be on the native 17k+5 grid at 24 fps')


def _filename(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 256
            or not value.endswith('.safetensors') or value != value.strip()
            or any(c in value for c in ('\x00', '\n', '\r', ':'))
            or value.startswith(('/', '\\'))
            or any(p in ('', '.', '..') for p in value.replace('\\', '/').split('/'))):
        raise ValueError('Model filename must be an explicit confined safetensors name')


def _models(models):
    if not isinstance(models, H3ContinuityModels):
        raise ValueError('All four effective model files and captured hashes are required')
    for weight in (models.unet, models.clip, models.video_vae, models.audio_vae):
        if not isinstance(weight, Weight):
            raise ValueError('An effective model is not a Weight')
        _filename(weight.filename)
        if weight.sha256 is not None and (not isinstance(weight.sha256, str)
                                          or not _HEX64.fullmatch(weight.sha256)):
            raise ValueError('A measured weight hash must be 64 lowercase hexadecimal characters')


def _reference(reference):
    if not isinstance(reference, dict) or reference.get('__type') != 'core/ASSET':
        raise ValueError('Exactly one committed SDK character reference is required; zero/multiple refs are out of scope')
    info = reference.get('info')
    identifier = info.get('id') if isinstance(info, dict) else None
    if not isinstance(identifier, str) or not _ASSET_ID.fullmatch(identifier):
        raise ValueError('Invalid committed SDK reference ID')
    return {'__type': 'core/ASSET', 'info': {'id': identifier}}


def _parent_clip(value):
    if (not isinstance(value, str) or not _PARENT_CLIP.fullmatch(value)
            or value != value.strip() or value.startswith(('/', '\\'))
            or any(part in ('', '.', '..') for part in value.replace('\\', '/').split('/'))):
        raise ValueError('Parent must be a verified output-relative native loader literal')


def _link(value):
    return (isinstance(value, list) and len(value) == 2
            and isinstance(value[0], str) and type(value[1]) is int)


def unconsumed_nodes(graph):
    """Dependency reachability from the two actual output nodes; no execution."""
    seen, active = set(), set()

    def visit(node):
        if node in active or node not in graph:
            raise ValueError('Cycle or dangling consumed link')
        if node in seen:
            return
        active.add(node)
        for value in graph[node]['inputs'].values():
            if _link(value):
                if value[1] < 0:
                    raise ValueError('Negative output slot')
                visit(value[0])
        active.remove(node)
        seen.add(node)

    visit('1216'); visit(HANDLE_NODE)
    return set(graph) - seen


# The ONLY mutable value locations. Topology mutations are limited to omitting
# unused parent pairs and choosing forward/reverse at the same native PinSpec.
_BINDINGS = {
    ('761:763', 'value'): 'PROMPT', ('761:1381', 'in_2'): 'WIDTH',
    ('761:1381', 'in_3'): 'HEIGHT', ('1449', 'in_1'): 'RAW_FRAMES',
    ('2004', 'value'): 'SEED', ('200', 'image'): 'REFERENCE',
    ('725', 'unet_name'): 'UNET', ('752:747', 'clip_name'): 'CLIP',
    ('752:748', 'vae_name'): 'VIDEO_VAE', ('752:798', 'vae_name'): 'AUDIO_VAE',
    ('761:1217', 'value'): 'OUTPUT_FOLDER', ('1216', 'metadata'): 'METADATA',
    (HANDLE_NODE, 'filename_prefix'): 'HANDLE_PREFIX',
}


def _set(graph, node, field, value):
    graph[node]['inputs'][field] = value


def _mode(graph, mode):
    if mode == 'root':
        for node in ('2010', '2011', '2020', '2021'):
            graph.pop(node)
        graph['1228']['inputs'].pop('pin_specs')
    elif mode in ('forward', 'reverse'):
        for node in ('2011', '2021'):
            graph.pop(node)
        _set(graph, '1228', 'pin_specs', ['2020', 0])
        if mode == 'reverse':
            _set(graph, '2020', 'take_from', 'head')
            _set(graph, '2020', 'place', 'after')
    elif mode != 'bridge':
        raise ValueError('mode must be root, forward, reverse or bridge')


def validate_consumed_links(graph):
    """Fail closed on any topology/static-control drift, including inert branches.

    This is intentionally stricter than a generic JSON/socket validator: a sampler
    wired around ApplyPins can be well-typed but silently discard continuity.
    """
    canonical_digest(graph)  # Explicitly rejects NaN/Infinity before comparison.
    expected = _load_template()
    actual = _loads(_canonical(graph))
    # An optional publication adapter may follow the saver. It is pinned exactly:
    # consuming the saver's clip slot, never some other output.
    published = actual.pop('native_family', None)
    if published is not None and published != {'class_type': 'OpenGenjutsuH3PublishClip',
                                               'inputs': {'clip': ['1216', 0]}}:
        raise ValueError('Native family publication must consume the saver clip')
    mode = ('bridge' if '2011' in actual else
            ('reverse' if actual.get('2020', {}).get('inputs', {}).get('place') == 'after'
             else 'forward') if '2010' in actual else 'root')
    _mode(expected, mode)
    try:
        inputs = lambda node: actual[node]['inputs']
        source_audio = None
        if 'source_audio' in actual:
            source_audio = _asset(inputs('source_audio')['audio'])
            if inputs('source_audio')['audio'] != source_audio:
                raise ValueError('Unresolved or noncanonical source audio')
            _bind_source_audio(expected, source_audio)
        _geometry(inputs('761:1381')['in_2'], inputs('761:1381')['in_3'], inputs('1449')['in_1'])
        _integer(inputs('2004')['value'], 'seed', 0, 2**64 - 1)
        prompt = inputs('761:763')['value']
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('An effective prompt is required')
        if inputs('200')['image'] != _reference(inputs('200')['image']):
            raise ValueError('Unresolved or noncanonical reference')
        for node, field in (('725', 'unet_name'), ('752:747', 'clip_name'),
                            ('752:748', 'vae_name'), ('752:798', 'vae_name')):
            _filename(inputs(node)[field])
        for node in ('2010', '2011'):
            if node in actual:
                _parent_clip(inputs(node)['clip'])
                actual[node]['inputs']['clip'] = expected[node]['inputs']['clip']
        # The ramp is a bounded choice, not topology: check it, then normalise so
        # the static comparison still catches any real drift.
        for node in ('2020', '2021'):
            if node in actual:
                frames = inputs(node).get('mask_ramp_frames')
                edge = inputs(node).get('mask_ramp_edge')
                if type(frames) is not int or not 0 <= frames <= 256:
                    raise ValueError('Invalid pin ramp length')
                if not isinstance(edge, (int, float)) or isinstance(edge, bool) \
                        or not 0.0 <= float(edge) <= 1.0:
                    raise ValueError('Invalid pin ramp edge')
                actual[node]['inputs']['mask_ramp_frames'] = \
                    expected[node]['inputs']['mask_ramp_frames']
                actual[node]['inputs']['mask_ramp_edge'] = \
                    expected[node]['inputs']['mask_ramp_edge']
        if published is not None:
            if inputs(HANDLE_NODE)['text'] != ['native_family', 0]:
                raise ValueError('Published family must feed the clip handle')
            actual[HANDLE_NODE]['inputs']['text'] = expected[HANDLE_NODE]['inputs']['text']
        folder = inputs('761:1217')['value']
        prefix = 'OpenGenjutsu/continuity/takes/'
        if not isinstance(folder, str) or not folder.startswith(prefix) or not _HEX32.fullmatch(folder[len(prefix):]):
            raise ValueError('Only server-operation-confined output folders are allowed')
        if inputs(HANDLE_NODE)['filename_prefix'] != f'OpenGenjutsu/continuity/handles/{folder[len(prefix):]}/clip':
            raise ValueError('Handle capture escaped its operation namespace')
        metadata = _loads(inputs('1216')['metadata'])
        if not isinstance(metadata, dict):
            raise ValueError('Frozen recipe metadata must be an object')
        if metadata.get('source_audio') != source_audio:
            raise ValueError('Source audio differs from the frozen recipe metadata')
        for node, field in _BINDINGS:
            actual[node]['inputs'][field] = expected[node]['inputs'][field]
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('Corrupted native continuity input contract') from exc
    if actual != expected or unconsumed_nodes(graph):
        raise ValueError('Native continuity consumed links/static controls differ from the pinned template')


def build_h3_continuity(mode, reference, prompt, *, operation_id, seed,
                        width, height, raw_frames, models, parents=(),
                        publish_family=False, ramp_frames=0, ramp_edge=0.0,
                        source_audio=None):
    """Compile a new native Take recipe; does not submit or approve a replay.

    operation_id must be generated by the trusted service (uuid4().hex), never a
    client path. parents must be a tuple of validated/restaged NativeH3Parent
    attestations, ordered A then B for bridge. Their capsules are provenance only.
    Target capability/model inventory validation is separately available below.
    source_audio optionally replaces only target audio, using a caller-prepared
    committed SDK asset; it does not attest source timing or perceptual lip-sync.
    """
    if mode not in ('root', 'forward', 'reverse', 'bridge'):
        raise ValueError('mode must be root, forward, reverse or bridge')
    if type(publish_family) is not bool:
        raise ValueError('Family publication must be an explicit boolean')
    # The pin holds the parent verbatim; a ramp gives the model a landing strip
    # instead of an instant switch. Zero means "hard join", the historical default.
    if type(ramp_frames) is not int or not 0 <= ramp_frames <= 256:
        raise ValueError('ramp_frames must be an integer between 0 and 256')
    if not isinstance(ramp_edge, (int, float)) or isinstance(ramp_edge, bool) \
            or not 0.0 <= float(ramp_edge) <= 1.0:
        raise ValueError('ramp_edge must be a number between 0 and 1')
    if not isinstance(operation_id, str) or not _HEX32.fullmatch(operation_id):
        raise ValueError('A server-generated 32-hex operation identifier is required')
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('A nonempty effective prompt is required')
    _geometry(width, height, raw_frames)
    _integer(seed, 'seed', 0, 2**64 - 1)
    _models(models)
    reference = _reference(reference)
    source_audio = _asset(source_audio) if source_audio is not None else None
    count = {'root': 0, 'forward': 1, 'reverse': 1, 'bridge': 2}[mode]
    if not isinstance(parents, tuple) or len(parents) != count:
        raise ValueError(f'{mode} requires exactly {count} explicit parent attestations')
    identities = set()
    for parent in parents:
        if not isinstance(parent, NativeH3Parent):
            raise ValueError('Explicit NativeH3Parent attestations are required')
        _parent_clip(parent.clip)
        _integer(parent.width, 'parent width', 32, 16384)
        _integer(parent.height, 'parent height', 32, 16384)
        _integer(parent.fps, 'parent fps', 24, 24)
        _integer(parent.delivered_frames, 'measured parent delivered_frames', PIN_WINDOW, 3600)
        if (not isinstance(parent.take_id, str) or not parent.take_id.strip()
                or len(parent.take_id) > 256 or '\x00' in parent.take_id
                or not isinstance(parent.capsule_digest, str) or not _HEX64.fullmatch(parent.capsule_digest)):
            raise ValueError('Captured parent lineage identity is required')
        _models(parent.models)
        if (parent.width, parent.height, parent.fps, parent.models) != (width, height, 24, models):
            raise ValueError('Native parent geometry/fps/effective weights differ from the target')
        if parent.take_id in identities or parent.clip in identities:
            raise ValueError('Bridge requires two distinct parents; loops are out of scope')
        identities.update((parent.take_id, parent.clip))
    if count and raw_frames <= count * PIN_WINDOW:
        raise ValueError('Pins must leave unpinned raw target frames for generation')
    anchors = ([{'parent_index': 0, 'take_from': 'tail', 'place': 'before', 'window': PIN_WINDOW}]
               if mode in ('forward', 'bridge') else
               [{'parent_index': 0, 'take_from': 'head', 'place': 'after', 'window': PIN_WINDOW}]
               if mode == 'reverse' else [])
    if mode == 'bridge':
        anchors.append({'parent_index': 1, 'take_from': 'head', 'place': 'after', 'window': PIN_WINDOW})
    record = {
        'version': RECIPE_VERSION, 'source_graph_digest': SOURCE_GRAPH_DIGEST,
        'template_digest': TEMPLATE_DIGEST, 'operation_id': operation_id,
        'mode': mode, 'seed': seed, 'prompt': prompt, 'reference': reference,
        'geometry': {'width': width, 'height': height, 'raw_frames': raw_frames, 'fps': 24},
        'models': asdict(models), 'parents': [asdict(parent) for parent in parents],
        'anchors': anchors,
        'validation': 'compiled-only; not rendered or approved for replay',
    }
    if source_audio is not None:
        record['source_audio'] = source_audio
    graph = _load_template()
    _mode(graph, mode)
    _bind_source_audio(graph, source_audio)
    if ramp_frames or ramp_edge:
        for node in ('2020', '2021'):
            if node in graph:
                _set(graph, node, 'mask_ramp_frames', ramp_frames)
                _set(graph, node, 'mask_ramp_edge', float(ramp_edge))
    values = dict(PROMPT=prompt, WIDTH=width, HEIGHT=height, RAW_FRAMES=raw_frames,
                  SEED=seed, REFERENCE=reference, UNET=models.unet.filename,
                  CLIP=models.clip.filename, VIDEO_VAE=models.video_vae.filename,
                  AUDIO_VAE=models.audio_vae.filename,
                  OUTPUT_FOLDER=f'OpenGenjutsu/continuity/takes/{operation_id}',
                  HANDLE_PREFIX=f'OpenGenjutsu/continuity/handles/{operation_id}/clip',
                  METADATA=_canonical(record))
    for (node, field), label in _BINDINGS.items():
        if graph[node]['inputs'][field] != f'__H3_BIND_{label}__':
            raise ValueError('Template binding sentinel mismatch')
        _set(graph, node, field, values[label])
    for index, parent in enumerate(parents):
        _set(graph, ('2010', '2011')[index], 'clip', parent.clip)
    validate_consumed_links(graph)
    if publish_family:
        # The stock saver returns a path, not SDK outputs. The same adapter the
        # Swap uses turns that path into three retrievable files, and the handle
        # then carries the published loader literal instead of the raw path.
        graph['native_family'] = {'class_type': 'OpenGenjutsuH3PublishClip',
                                  'inputs': {'clip': ['1216', 0]}}
        graph[HANDLE_NODE]['inputs']['text'] = ['native_family', 0]
    record.update(graph=graph, graph_digest=canonical_digest(graph), publication={
        'saver_node': '1216', 'clip_output_slot': 0, 'handle_node': HANDLE_NODE,
        'family_assets_published': bool(publish_family),
        'family_node': 'native_family' if publish_family else None,
        'requires_verified_family_publication': True,
    })
    return ContinuityRecipe(_canonical(record))


def _resolved_literal(graph, node, slot=0):
    """Resolve only existing native bundle/preset routing for COMBO checks.

    Unbundle's wildcard output can legally carry a selected literal into a COMBO
    in the inspected graph. This is NOT permission to connect a STRING restager
    to the native loader's filename COMBO.
    """
    n = graph[node]; inputs = n['inputs']; kind = n['class_type']
    if kind == 'ValuePresets (obvpm)':
        return _loads(inputs['values'])
    if kind == 'Bundle (obvpm)':
        return {name: _resolve_value(graph, inputs.get(f'in_{i+1}'))
                for i, name in enumerate(inputs['names'].splitlines())}
    if kind == 'Unbundle (obvpm)':
        bundle = _resolve_value(graph, inputs['in'])
        names = inputs['names'].splitlines() or list(bundle)
        return bundle.get(names[slot])
    if kind == 'LazySwitch (obvpm)':
        return _resolve_value(graph, inputs['on_true' if _resolve_value(graph, inputs['boolean']) else 'on_false'])
    if kind in ('PrimitiveBoolean', 'PrimitiveString', 'PrimitiveStringMultiline', 'INTConstant'):
        return inputs['value']
    raise ValueError(f'No literal provenance for {node}[{slot}]')


def _resolve_value(graph, value):
    return _resolved_literal(graph, *value) if _link(value) else value


def validate_graph_contracts(graph, object_info):
    """Read-only installed-schema check of the *built* SDK graph, no network.

    Supply a fresh GET /object_info inventory. This checks known input fields,
    required fields, output slots/types, enums (including routed sampler literals)
    and scalar bounds. Committed LoadImage assets are validated before proxy
    rewriting, not falsely checked against a target's current filename dropdown.
    Wildcard native routing is also protected by validate_consumed_links.
    Neither filesystem availability nor GPU/runtime/quality is proven by this.
    """
    validate_consumed_links(graph)
    for node, item in graph.items():
        kind, inputs = item['class_type'], item['inputs']
        if kind not in object_info:
            raise ValueError(f'Missing installed node class {kind}')
        contract = object_info[kind]
        sections = contract['input']
        specs = dict(sections.get('required', {})) | dict(sections.get('optional', {}))
        missing = set(sections.get('required', {})) - inputs.keys()
        if missing:
            raise ValueError(f'{node} missing required fields: {sorted(missing)}')
        for field, value in inputs.items():
            spec = specs.get(field)
            if spec is None and kind == 'ValuePresets (obvpm)' and field in _loads(inputs['values']):
                continue  # Fields generated by the pinned native preset schema.
            if spec is None and '.' in field:
                group, member = field.split('.', 1)
                dynamic = specs.get(group)
                if dynamic and dynamic[0] == 'COMFY_AUTOGROW_V3':
                    spec = autogrow_member_spec(dynamic, member)
            if spec is None:
                raise ValueError(f'{node} has unknown installed input {field}')
            typ = spec[0]; options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            enum = typ if isinstance(typ, list) else options.get('options') if typ == 'COMBO' else None
            if _link(value):
                upstream, slot = value
                outputs = object_info[graph[upstream]['class_type']]['output']
                if not 0 <= slot < len(outputs):
                    raise ValueError(f'{node}.{field} references a missing output slot')
                received = outputs[slot]
                if enum is not None:
                    if received != '*':
                        raise ValueError(f'{node}.{field} filename/enum COMBO cannot consume {received}')
                    value = _resolved_literal(graph, upstream, slot)
                elif received != '*' and typ != '*' and received != typ:
                    raise ValueError(f'{node}.{field} type mismatch {received} -> {typ}')
                else:
                    continue
            if kind == 'LoadImage' and field == 'image':
                _reference(value)
                continue
            if kind == 'LoadAudio' and field == 'audio':
                _asset(value)
                continue  # SDK resolves this asset before filename COMBO validation.
            if enum is not None:
                if value not in enum:
                    raise ValueError(f'{node}.{field} literal is absent from installed options')
            elif typ == 'INT':
                _integer(value, f'{node}.{field}', options.get('min', -(2**64)), options.get('max', 2**64-1))
            elif typ == 'FLOAT':
                if type(value) not in (int, float) or not options.get('min', float('-inf')) <= value <= options.get('max', float('inf')):
                    raise ValueError(f'{node}.{field} is outside installed numeric bounds')
            elif typ == 'BOOLEAN' and type(value) is not bool:
                raise ValueError(f'{node}.{field} must be boolean')
            elif typ == 'STRING' and not isinstance(value, str):
                raise ValueError(f'{node}.{field} must be string')
    return {'nodes': len(graph), 'classes': len({n['class_type'] for n in graph.values()}),
            'validation': 'static installed schema only; no submission'}
