"""Versioned content-neutral H3 prompt policy and frozen render configuration."""
from dataclasses import asdict
import copy
import hashlib
import json
from h3_graphs import H3Models, build_h3_recast, h3_frames

ENGINE = 'minimax-h3'
POLICY = 'h3-recast-v1'
INPUT_LONG_EDGE = 512
OUTPUT_SCALE = 2
BASE_PROMPT = (
    'Replace the main performer in <Video 1> with the character appearance from '
    '<Picture 1>. Use <Picture 1> for appearance, clothing and identity. Use '
    '<Video 1> for performance, motion, pose, timing and camera movement. Preserve '
    'the source environment, framing and interactions. Keep the reference '
    'appearance consistent throughout the single continuous shot.'
)


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


def make_recipe(edit_prompt='', seed=302929098223082, *, source_width, source_height):
    if not isinstance(edit_prompt, str) or len(edit_prompt) > 2000:
        raise ValueError('Edit directions must contain at most 2000 characters')
    width, height = h3_dimensions(source_width, source_height)
    effective = BASE_PROMPT + ('\nAdditional directions: ' + edit_prompt if edit_prompt.strip() else '')
    recipe = {
        'schema_version': 1, 'engine': ENGINE, 'prompt_policy': POLICY,
        'user_edit_prompt': edit_prompt, 'effective_prompt': effective,
        'seed': seed, 'fps': 24, 'single_shot_only': True,
        'preserve_source_audio': True, 'reference_size': 'match',
        'width': width, 'height': height,
        'output_width': width * OUTPUT_SCALE, 'output_height': height * OUTPUT_SCALE,
        'steps': 6, 'split_step': 3, 'model_files': asdict(H3Models()),
        'source_width': source_width, 'source_height': source_height, 'source_frames_24fps': None, 'inference_frames': None,
    }
    validate_recipe(recipe)
    return recipe


def bind_frames(recipe, count, source_audio=False):
    """Freeze the fully resolved graph with path-free asset placeholders."""
    recipe = copy.deepcopy(recipe)
    padded = h3_frames(count)
    if source_audio:
        raise ValueError('H3 Studio requires silent normalized conditioning; original audio is muxed locally')
    recipe['source_frames_24fps'], recipe['inference_frames'] = count, padded
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
    if (recipe.get('schema_version') != 1 or recipe.get('engine') != ENGINE
            or recipe.get('prompt_policy') != POLICY or recipe.get('fps') != 24
            or recipe.get('single_shot_only') is not True
            or recipe.get('preserve_source_audio') is not True):
        raise ValueError('Unsupported H3 recipe contract')
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
        if (graph.get('155', {}).get('inputs', {}).get('frame_load_cap') != h3_frames(count)
                or graph.get('136', {}).get('inputs', {}).get('length') != h3_frames(count)
                or graph.get('136', {}).get('inputs', {}).get('prompt') != recipe['effective_prompt']
                or graph.get('129', {}).get('inputs', {}).get('noise_seed') != recipe['seed']):
            raise ValueError('Frozen H3 graph does not match the recipe')
    return copy.deepcopy(recipe)
