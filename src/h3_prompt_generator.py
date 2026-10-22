"""Turn a human direction into a structured H3 R2VA prompt.

The policy already exists as a ComfyUI workflow: a local Qwen3-4B reads the
Full-Reference Mode guide, the direction and one reference image, and writes the
prompt. This module only fills the user-owned slot, keeps the policy text byte for
byte, and captures the produced text through an actual SDK output.

It does not invent a prompt policy and does not run on the CPU: generation needs
the target's text model.
"""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import re

TEMPLATE = Path(__file__).resolve().parents[1] / 'workflows/h3-prompt-r2va.api.json'
POLICY_VERSION = 'h3-r2va-v1'
OUTPUT_NODE = 'prompt_text'
DIRECTION_NODE = '5833_15'      # the user-owned subject/description slot
MODE_NODE = '5833_28'           # from-prompt | rewrite
REFERENCE_NODE = '5836'
BATCH_NODE = '5837'
GENERATE_NODE = '5833_6'
CLIP_NODE = '5833_23'
PREVIEW_NODES = ('5839', '5833_14', '5833_7')
UNUSED_NODES = ('5838',)
MODES = ('from-prompt', 'rewrite')
INSTRUCTIONS = {
    'from-prompt': ('Create a Full-Reference Mode (R2VA) prompt with the following '
                    'subjects and description:'),
    'rewrite': 'Rewrite the following prompt to adhere to the Full-Reference Mode (R2VA) prompt guide:',
}
MAX_DIRECTION = 4000
MAX_PROMPT_BYTES = 20000
_ASSET = re.compile(r'[A-Za-z0-9_.:-]{1,256}\Z')
_MODEL = re.compile(r'[A-Za-z0-9_./-]{1,256}\Z')

# The guide defines labels from what the text says, not from what the model sees.
# Without this line the generator answers that no reference assets were provided
# and never cites the attached picture. The wording follows the guide's own
# subject-definition form instead of inventing a new syntax.
REFERENCE_DECLARATION = (
    '<Subject 1> is the person shown in the attached reference image <Picture 1>, '
    'whose appearance must be preserved.')


def _asset(value):
    info = value.get('info') if isinstance(value, dict) else None
    identifier = info.get('id') if isinstance(info, dict) else None
    if (not isinstance(value, dict) or value.get('__type') != 'core/ASSET'
            or not isinstance(identifier, str) or not _ASSET.fullmatch(identifier)):
        raise ValueError('The prompt reference must be a committed SDK asset')
    return {'__type': 'core/ASSET', 'info': {'id': identifier}}


def policy_text() -> str:
    """The frozen guide. Exposed so a test can prove it is never rewritten."""
    return json.loads(TEMPLATE.read_text())['5833_26']['inputs']['string']


def build_prompt_graph(direction: str, references, *, mode: str = 'from-prompt',
                       clip_name: str | None = None,
                       filename_prefix: str = 'OpenGenjutsu/prompts/h3') -> dict:
    """Compile the prompt job exactly as the authored workflow runs it.

    ``from-prompt`` is the authored mode: the guide builds its six sections from
    the attached pictures plus whatever the operator wrote, which may be nothing.
    The ``rewrite`` default was our invention and turned a hand-written
    declaration into a full new-video description.
    """
    if not isinstance(direction, str) or not direction.strip():
        raise ValueError('A direction is required; an empty one makes the guide '
                         'copy its own example')
    if len(direction) > MAX_DIRECTION:
        raise ValueError(f'A direction is limited to {MAX_DIRECTION} characters')
    if mode not in MODES:
        raise ValueError(f'Mode must be one of {MODES}')
    if isinstance(references, (dict, str)):
        references = [references]
    if not isinstance(references, (list, tuple)) or not references:
        raise ValueError('At least one reference image is required')
    graph = copy.deepcopy(json.loads(TEMPLATE.read_text()))

    # The operator's words go in untouched; empty is legitimate, the guide
    # describes the pictures on its own.
    graph[DIRECTION_NODE]['inputs']['string'] = direction.strip()
    graph[MODE_NODE]['inputs']['choice'] = mode
    if clip_name is not None:
        if not isinstance(clip_name, str) or not _MODEL.fullmatch(clip_name):
            raise ValueError('clip_name must be a plain model filename')
        graph[CLIP_NODE]['inputs']['clip_name'] = clip_name
    graph[REFERENCE_NODE]['inputs']['image'] = _asset(references[0])

    # The installed ImageBatchMulti requires at least two images. With one
    # reference the same asset fills both slots; with several, each is attached.
    batch = graph[BATCH_NODE]['inputs']
    extra = list(references[1:])
    for position, asset in enumerate(extra, start=2):
        graph[f'{REFERENCE_NODE}_{position}'] = {
            'class_type': 'LoadImage', 'inputs': {'image': _asset(asset)}}
    batch['inputcount'] = max(2, len(references))
    batch['image_1'] = [REFERENCE_NODE, 0]
    batch['image_2'] = [f'{REFERENCE_NODE}_2', 0] if extra else [REFERENCE_NODE, 0]
    for position in range(3, len(references) + 1):
        batch[f'image_{position}'] = [f'{REFERENCE_NODE}_{position}', 0]
    for node in (*PREVIEW_NODES, *UNUSED_NODES):
        graph.pop(node, None)

    # The produced text is read back through a real SDK output, never a preview.
    graph[OUTPUT_NODE] = {'class_type': 'SaveText', 'inputs': {
        'text': [GENERATE_NODE, 0], 'format': 'txt',
        'filename_prefix': filename_prefix,
    }}
    return graph


class _BoundedText:
    def __init__(self):
        self.data = io.BytesIO()

    def write(self, block):
        if len(block) > MAX_PROMPT_BYTES - self.data.tell():
            raise ValueError('Generated prompt exceeded its byte limit')
        return self.data.write(block)


def read_prompt_text(job, node: str = OUTPUT_NODE) -> str:
    """Read the exact generated text from an actual SDK output."""
    from comfy_sdk.outputs import Output

    if getattr(job, 'status', None) != 'succeeded' or not isinstance(getattr(job, 'id', None), str):
        raise ValueError('A succeeded prompt job is required')
    outputs = list(job.get_outputs(node) or [])
    if len(outputs) != 1 or not isinstance(outputs[0], Output):
        raise ValueError('Exactly one generated prompt output is required')
    output = outputs[0]
    if (output.node_id != node or output.job_id != job.id
            or not isinstance(output.name, str) or not output.name.endswith('.txt')
            or any(c in output.name for c in ('/', '\\', '\x00'))
            or output.type not in {'file', 'text'}
            or type(output.size_bytes) is not int or not 0 <= output.size_bytes <= MAX_PROMPT_BYTES):
        raise ValueError('Generated prompt output identity or metadata is invalid')
    sink = _BoundedText()
    output.to_stream(sink)
    raw = sink.data.getvalue()
    # A real output can report size 0 while carrying a full file. Only compare
    # when the target actually declares a size, otherwise every such job fails.
    if not raw or (output.size_bytes and len(raw) != output.size_bytes):
        raise ValueError('Generated prompt size differs from its output metadata')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError('Generated prompt is not UTF-8') from None
    if not text.strip():
        raise ValueError('Generated prompt is empty')
    return text



# The Swap already loads this model to describe references. Reusing it means no
# second download for a feature that only writes text.
VL_NODE = 'AILab_QwenVL'
VL_MODEL = 'Qwen3-VL-2B-Instruct'
VL_QUANTIZATION = '4-bit (VRAM-friendly)'


def build_vl_prompt_graph(direction: str, reference: dict, *, model: str = VL_MODEL,
                          quantization: str = VL_QUANTIZATION, max_tokens: int = 2048,
                          seed: int = 1, mode: str = 'from-prompt',
                          filename_prefix: str = 'OpenGenjutsu/prompts/h3') -> dict:
    """The same three blocks, run on the vision model the Swap already loads.

    Identical composition to ``build_prompt_graph`` so a comparison measures the
    model and nothing else: guide, instruction, operator text.
    """
    if not isinstance(direction, str) or not direction.strip():
        raise ValueError('A direction is required')
    if len(direction) > MAX_DIRECTION:
        raise ValueError(f'A direction is limited to {MAX_DIRECTION} characters')
    if mode not in MODES:
        raise ValueError(f'Mode must be one of {MODES}')
    if type(max_tokens) is not int or not 64 <= max_tokens <= 2048:
        raise ValueError('max_tokens must be an integer between 64 and 2048')
    if type(seed) is not int or not 1 <= seed <= 4294967295:
        raise ValueError('seed must be an integer between 1 and 4294967295')

    instruction = f'{policy_text()}\n{INSTRUCTIONS[mode]}\n{direction.strip()}'
    return {
        'reference': {'class_type': 'LoadImage', 'inputs': {'image': _asset(reference)}},
        VL_NODE: {'class_type': VL_NODE, 'inputs': {
            'model_name': model, 'quantization': quantization,
            'attention_mode': 'auto', 'preset_prompt': '🖼️ Detailed Description',
            'custom_prompt': instruction, 'max_tokens': max_tokens,
            'keep_model_loaded': False, 'seed': seed, 'image': ['reference', 0],
        }},
        OUTPUT_NODE: {'class_type': 'SaveText', 'inputs': {
            'text': [VL_NODE, 0], 'format': 'txt', 'filename_prefix': filename_prefix,
        }},
    }
