"""Versioned content-neutral H3 prompt policy and frozen render configuration.

Prompt policy v2 adopts the structured scaffold that won the measured A/B arm
``proven_audio``: an explicit <Subject 1> / <Picture 1> / <Video 1> role split,
a replace-only instruction, an explicit preservation list and explicit negative
constraints, plus source-audio conditioning. The character description and the
edit directions are user-owned text and are never invented by a model.
Policy v1 (one generic sentence, silent conditioning) is rejected.
"""
from dataclasses import asdict
import copy
import hashlib
import json
from h3_graphs import H3Models, build_h3_recast, h3_frames

ENGINE = 'minimax-h3'
POLICY = 'h3-recast-v2'
INPUT_LONG_EDGE = 512
OUTPUT_SCALE = 2
MAX_TEXT = 2000
SUBJECT_CLAUSE = (
    '<Subject 1> is the replacement character whose appearance is shown in '
    '<Picture 1>{descriptor}.'
)
PRESERVATION_CLAUSE = (
    '<Video 1> supplies the source performance, scene, framing, timing and camera motion.\n'
    'Replace only the main performer in <Video 1> with <Subject 1>. Keep the original '
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


def compose_prompt(character_description='', edit_prompt=''):
    """Build the effective prompt from deterministic, user-owned text only."""
    descriptor = _text(character_description, 'Character description').strip()
    clause = SUBJECT_CLAUSE.format(descriptor=f': {descriptor}' if descriptor else '')
    parts = [clause, PRESERVATION_CLAUSE]
    directions = _text(edit_prompt, 'Edit directions').strip()
    if directions:
        parts.append('Additional directions: ' + directions)
    return '\n'.join(parts)


def h3_dimensions(source_width, source_height):
    """Choose the closest 32-aligned H3 canvas to the source aspect ratio."""
    if type(source_width) is not int or type(source_height) is not int or min(source_width, source_height) <= 0:
        raise ValueError('Source dimensions must be positive integers')
    ratio = source_width / source_height
    if not 1 / 8 <= ratio <= 8:
        raise ValueError('H3 supports source aspect ratios between 1:8 and 8:1')
    choices = [(w, h) for w in range(64, INPUT_LONG_EDGE + 1, 32)
               for h in range(64, INPUT_LONG_EDGE + 1, 32)]
    return min(choices, key=lambda size: (abs((size[0] / size[1]) / ratio - 1),
                                         -(size[0] * size[1])))


def digest_json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def make_recipe(edit_prompt='', seed=302929098223082, *, character_description='',
                source_width, source_height):
    width, height = h3_dimensions(source_width, source_height)
    directions = _text(edit_prompt, 'Edit directions')
    description = _text(character_description, 'Character description')
    recipe = {
        'schema_version': 2, 'engine': ENGINE, 'prompt_policy': POLICY,
        'character_description': description, 'user_edit_prompt': directions,
        'effective_prompt': compose_prompt(description, directions),
        'seed': seed, 'fps': 24, 'single_shot_only': True,
        'preserve_source_audio': True, 'source_audio_conditioning': True,
        'reference_size': 'match',
        'width': width, 'height': height,
        'output_width': width * OUTPUT_SCALE, 'output_height': height * OUTPUT_SCALE,
        'steps': 6, 'split_step': 3, 'model_files': asdict(H3Models()),
        'source_width': source_width, 'source_height': source_height, 'source_frames_24fps': None, 'inference_frames': None,
    }
    validate_recipe(recipe)
    return recipe


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
        'h3-source-placeholder', 'h3-reference-placeholder', recipe['effective_prompt'],
        source_frames=padded, source_audio=source_audio, **graph_options(recipe))
    return validate_recipe(recipe)


def graph_options(recipe):
    return {key: recipe[key] for key in ('seed', 'width', 'height', 'output_width',
            'output_height', 'steps', 'split_step', 'reference_size')} | {
                'models': H3Models(**recipe['model_files'])}


def validate_recipe(recipe):
    if (recipe.get('schema_version') != 2 or recipe.get('engine') != ENGINE
            or recipe.get('prompt_policy') != POLICY or recipe.get('fps') != 24
            or recipe.get('single_shot_only') is not True
            or recipe.get('preserve_source_audio') is not True
            or recipe.get('source_audio_conditioning') is not True):
        raise ValueError('Unsupported H3 recipe contract')
    if recipe.get('effective_prompt') != compose_prompt(
            recipe.get('character_description', ''), recipe.get('user_edit_prompt', '')):
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
    build_h3_recast('video', 'reference', recipe['effective_prompt'],
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
        conditioning = recipe.get('source_audio')
        if conditioning is not None and (
                ('audio' in node_inputs.get('156', {})) is not conditioning
                or ('ref_video_audios.ref_video_audio_0' in node_inputs.get('136', {})) is not conditioning):
            raise ValueError('Frozen H3 graph audio conditioning does not match the recipe')
    return copy.deepcopy(recipe)
