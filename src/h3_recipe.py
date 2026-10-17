"""Versioned content-neutral H3 prompt policy and frozen render configuration.

Prompt policy v3 keeps the scaffold that won the measured A/B arm ``proven_audio``
(<Subject N> / <Picture N> / <Video 1> roles, a replace-only rule, a preservation
list and negative constraints, plus source-audio conditioning) and extends it to two
ordered character references, mirroring the sample workflow's ``subject_definitions``
shape.

Each reference carries its own description and its provenance: text typed by the user
is recorded as 'user', text completed by the local vision model is recorded as
'generated'. A generated description is never silent — it is frozen into the recipe,
so a take stays reproducible and auditable. Nothing about the source video is ever
invented. Policies v1 and v2 are rejected.
"""
from dataclasses import asdict
import copy
import hashlib
import json
import math
from h3_graphs import H3Models, REFERENCE_NODE, REFERENCE_SLOTS, build_h3_recast, h3_frames

ENGINE = 'minimax-h3'
POLICY = 'h3-recast-v3'
# LTX's quality card promises ~0.9 MP aspect-aware. H3 targets the same output size so
# the two studios stay coherent; the input canvas follows from it.
TARGET_OUTPUT_MEGAPIXELS = 0.9
OUTPUT_ALIGN = 64
MIN_SIDE = 64
OUTPUT_SCALE = 2
MAX_TEXT = 2000
DESCRIPTION_SOURCES = ('user', 'generated')
PRESERVE_SOURCES = ('none', 'user', 'generated')
SUBJECT_CLAUSE = (
    '<Subject {index}> is the replacement character whose appearance is shown in '
    '<Picture {index}>{descriptor}.'
)
PRESERVATION_CLAUSE = (
    '<Video 1> supplies the source performance, scene, framing, timing and camera motion.\n'
    'Replace only the main performer{s} in <Video 1> with {subjects}. Keep the original '
    'performance, poses, gestures, framing, environment, camera movement and lighting from '
    "<Video 1>. Use <Picture 1> only for the replacement character's identity, build and "
    'clothing; do not reproduce its layout, background, extra poses or props. Do not invent '
    'actions, people, cuts or objects. Preserve the source soundtrack and keep the replacement '
    'stable throughout the shot.'
)


def _text(value, name):
    if not isinstance(value, str):
        raise ValueError(f'{name} must be text')
    if len(value) > MAX_TEXT:
        raise ValueError(f'{name} must contain at most {MAX_TEXT} characters')
    return value


def _descriptions(reference_descriptions):
    if isinstance(reference_descriptions, str):
        items = [reference_descriptions]
    elif isinstance(reference_descriptions, (list, tuple)):
        items = list(reference_descriptions)
    else:
        raise ValueError('Reference descriptions must be text or a sequence of text')
    if not 1 <= len(items) <= REFERENCE_SLOTS:
        raise ValueError(f'H3 accepts between 1 and {REFERENCE_SLOTS} reference descriptions')
    return [_text(item, 'Reference description') for item in items]


def _sources(reference_sources, count):
    if reference_sources is None:
        return ['user'] * count
    if not isinstance(reference_sources, (list, tuple)) or len(reference_sources) != count:
        raise ValueError('Reference description provenance must match the reference count')
    if any(source not in DESCRIPTION_SOURCES for source in reference_sources):
        raise ValueError('Reference description provenance must be user or generated')
    return list(reference_sources)


def compose_prompt(reference_descriptions=('',), preserve_clip=''):
    """Build the effective prompt from deterministic, frozen text only."""
    texts = _descriptions(reference_descriptions)
    subjects = ' and '.join(f'<Subject {index + 1}>' for index in range(len(texts)))
    parts = [
        SUBJECT_CLAUSE.format(index=index + 1,
                              descriptor=f': {text.strip()}' if text.strip() else '')
        for index, text in enumerate(texts)
    ]
    parts.append(PRESERVATION_CLAUSE.format(s='s' if len(texts) > 1 else '', subjects=subjects))
    preserved = _text(preserve_clip, 'Preserved clip description').strip()
    if preserved:
        parts.append('Additional directions: ' + preserved)
    return '\n'.join(parts)


def _source_ratio(source_width, source_height):
    if type(source_width) is not int or type(source_height) is not int or min(source_width, source_height) <= 0:
        raise ValueError('Source dimensions must be positive integers')
    ratio = source_width / source_height
    if not 1 / 8 <= ratio <= 8:
        raise ValueError('H3 supports source aspect ratios between 1:8 and 8:1')
    return ratio


def h3_output_dimensions(source_width, source_height):
    """Closest 64-aligned canvas at the source aspect ratio, near the target megapixels.

    Aligning the output to 64 keeps the derived input canvas on H3's 32 grid.
    """
    ratio = _source_ratio(source_width, source_height)
    target_pixels = TARGET_OUTPUT_MEGAPIXELS * 1_000_000
    ideal_width = math.sqrt(target_pixels * ratio)
    snap = lambda value: max(MIN_SIDE, int(round(value / OUTPUT_ALIGN)) * OUTPUT_ALIGN)
    return snap(ideal_width), snap(target_pixels / ideal_width)


def h3_dimensions(source_width, source_height):
    """H3 input canvas: half the target output canvas on each axis.

    The canvas follows the source aspect ratio and the shared 0.9 MP output target,
    instead of a fixed square-ish cap that starved portrait sources.
    """
    width, height = h3_output_dimensions(source_width, source_height)
    return width // OUTPUT_SCALE, height // OUTPUT_SCALE


def digest_json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def make_recipe(preserve_clip='', seed=302929098223082, *, reference_descriptions=('',),
                reference_sources=None, preserve_clip_source=None, source_width, source_height):
    width, height = h3_dimensions(source_width, source_height)
    preserved = _text(preserve_clip, 'Preserved clip description')
    descriptions = _descriptions(reference_descriptions)
    sources = _sources(reference_sources, len(descriptions))
    preserve_source = preserve_clip_source or ('user' if preserved.strip() else 'none')
    if preserve_source not in PRESERVE_SOURCES:
        raise ValueError('Preserved clip provenance must be none, user or generated')
    if preserve_source == 'none' and preserved.strip():
        raise ValueError('Preserved clip text needs a provenance')
    recipe = {
        'schema_version': 3, 'engine': ENGINE, 'prompt_policy': POLICY,
        'reference_count': len(descriptions),
        'reference_descriptions': descriptions, 'reference_description_sources': sources,
        'preserve_clip': preserved, 'preserve_clip_source': preserve_source,
        'effective_prompt': compose_prompt(descriptions, preserved),
        'seed': seed, 'fps': 24, 'single_shot_only': True,
        'preserve_source_audio': True, 'source_audio_conditioning': True,
        'reference_size': 'match',
        'width': width, 'height': height,
        'output_width': width * OUTPUT_SCALE, 'output_height': height * OUTPUT_SCALE,
        'steps': 6, 'split_step': 3, 'model_files': asdict(H3Models()),
        'source_width': source_width, 'source_height': source_height,
        'source_frames_24fps': None, 'inference_frames': None,
    }
    validate_recipe(recipe)
    return recipe


def with_preserve_clip(recipe, text, source='generated'):
    """Complete a recipe with a preserved-content description produced from the clip.

    Called before the graph is frozen, so the frozen template and the capsule both carry
    the text and its provenance. The user's own text is never overwritten.
    """
    if source not in DESCRIPTION_SOURCES:
        raise ValueError('Preserved clip provenance must be user or generated')
    updated = copy.deepcopy(recipe)
    if updated.get('preserve_clip_source') == 'user':
        raise ValueError('A recipe with the operator text is not overwritten')
    updated['preserve_clip'] = _text(text, 'Preserved clip description')
    updated['preserve_clip_source'] = source
    updated['effective_prompt'] = compose_prompt(updated['reference_descriptions'],
                                                updated['preserve_clip'])
    return validate_recipe(updated)


def reference_placeholders(count):
    return [f'h3-reference-placeholder-{index}' for index in range(count)]


def bind_frames(recipe, count, source_audio=True):
    """Freeze the fully resolved graph with path-free asset placeholders.

    ``source_audio`` is the measured fact about the prepared conditioning clip and
    must match the frozen graph: the reference node and the combine node carry it.
    """
    recipe = copy.deepcopy(recipe)
    padded = h3_frames(count)
    if type(source_audio) is not bool:
        raise ValueError('source_audio must be boolean')
    recipe['source_frames_24fps'], recipe['inference_frames'] = count, padded
    recipe['source_audio'] = source_audio
    recipe['shot_plan'] = [{'start': 0, 'end': count-1, 'fps': 24}]
    recipe['graph_template'] = build_h3_recast(
        'h3-source-placeholder', reference_placeholders(recipe['reference_count']),
        recipe['effective_prompt'], source_frames=padded, source_audio=source_audio,
        **graph_options(recipe))
    return validate_recipe(recipe)


def graph_options(recipe):
    return {key: recipe[key] for key in ('seed', 'width', 'height', 'output_width',
            'output_height', 'steps', 'split_step', 'reference_size')} | {
                'models': H3Models(**recipe['model_files'])}


def validate_recipe(recipe):
    if (recipe.get('schema_version') != 3 or recipe.get('engine') != ENGINE
            or recipe.get('prompt_policy') != POLICY or recipe.get('fps') != 24
            or recipe.get('single_shot_only') is not True
            or recipe.get('preserve_source_audio') is not True
            or recipe.get('source_audio_conditioning') is not True):
        raise ValueError('Unsupported H3 recipe contract')
    try:
        descriptions = _descriptions(recipe.get('reference_descriptions', ()))
        sources = _sources(recipe.get('reference_description_sources'), len(descriptions))
    except ValueError as exc:
        raise ValueError('Invalid H3 reference descriptions') from exc
    if recipe.get('reference_count') != len(descriptions) or sources != list(
            recipe.get('reference_description_sources', ())):
        raise ValueError('H3 reference count does not match the frozen descriptions')
    if recipe.get('preserve_clip_source') not in PRESERVE_SOURCES:
        raise ValueError('Invalid preserved clip provenance')
    if (recipe['preserve_clip'].strip() == '') is not (recipe['preserve_clip_source'] == 'none'):
        raise ValueError('Preserved clip text and provenance disagree')
    if recipe.get('effective_prompt') != compose_prompt(descriptions, recipe.get('preserve_clip', '')):
        raise ValueError('H3 effective prompt does not match the frozen policy text')
    models = recipe['model_files']
    if set(models) != set(asdict(H3Models())) or any(
            not isinstance(v, str) or not v or v.startswith(('/', '\\'))
            or '..' in v.replace('\\', '/').split('/') or '://' in v for v in models.values()):
        raise ValueError('Invalid H3 model filenames')
    try:
        expected_size = h3_dimensions(recipe['source_width'], recipe['source_height'])
    except (KeyError, ValueError) as exc:
        raise ValueError('Invalid H3 source dimensions') from exc
    if ((recipe['width'], recipe['height']) != expected_size
            or recipe['output_width'] != recipe['width'] * OUTPUT_SCALE
            or recipe['output_height'] != recipe['height'] * OUTPUT_SCALE):
        raise ValueError('H3 render dimensions do not match the source aspect ratio policy')
    # Before normalization there is no source frame count yet; this graph is
    # validation-only. The runner binds and freezes the actual measured count.
    build_h3_recast('video', reference_placeholders(len(descriptions)), recipe['effective_prompt'],
                    source_frames=recipe.get('inference_frames') or 5, **graph_options(recipe))
    count = recipe['source_frames_24fps']
    if count is not None:
        if recipe['inference_frames'] != h3_frames(count):
            raise ValueError('Invalid H3 frame grid')
        if recipe.get('shot_plan') != [{'start': 0, 'end': count-1, 'fps': 24}]:
            raise ValueError('H3 Studio supports exactly one full continuous shot')
        graph = recipe.get('graph_template', {})
        node_inputs = {key: value.get('inputs', {}) for key, value in graph.items()}
        if (node_inputs.get('155', {}).get('frame_load_cap') != h3_frames(count)
                or node_inputs.get('136', {}).get('length') != h3_frames(count)
                or node_inputs.get('136', {}).get('prompt') != recipe['effective_prompt']
                or node_inputs.get('129', {}).get('noise_seed') != recipe['seed']):
            raise ValueError('Frozen H3 graph does not match the recipe')
        for index in range(len(descriptions)):
            if node_inputs.get('136', {}).get(f'ref_images.ref_image_{index}') != [str(REFERENCE_NODE + index), 0]:
                raise ValueError('Frozen H3 graph reference slots do not match the recipe')
        conditioning = recipe.get('source_audio')
        if conditioning is not None and (
                ('audio' in node_inputs.get('156', {})) is not conditioning
                or ('ref_video_audios.ref_video_audio_0' in node_inputs.get('136', {})) is not conditioning):
            raise ValueError('Frozen H3 graph audio conditioning does not match the recipe')
    return copy.deepcopy(recipe)
