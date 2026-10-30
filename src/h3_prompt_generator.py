"""Turn a human direction into a structured H3 R2VA prompt.

The policy already exists as a ComfyUI workflow: a local vision Qwen 4B reads the
Full-Reference Mode guide, the direction and ordered images, and writes the
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

TEMPLATE = Path(__file__).resolve().parents[1] / 'workflows/h3-prompt-r2va.template.json'
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


# Measured on the existing node/model; the authored guide stays unchanged.
CONTINUATION_SYSTEM_PROMPT = '''You faithfully adapt the user's creative direction into the supplied reference guide's output format. The guide specifies notation, not a new story or an obligatory shot count. The user's explicit choices of shot structure, timing, camera motion, casting, setting, style and soundtrack are hard constraints.
A shot is one uninterrupted camera recording. Changes of pose, action, framing, or a continuous camera move are phases within that shot, not reasons to create another shot. When the user requests a single continuous shot or no cuts, use only [Shot 1] throughout all sections, with no cut timestamp or preliminary static establishing shot. Keep the complete requested camera move inside that shot.
When the user explicitly requests multiple shots, honor the requested number, order and cut times; do not force a single shot. Do not introduce extra cuts or reset the scene. Reference-guide examples are examples, never additional user instructions.
Describe the actual supplied subjects and source context. Cite only references supplied to the target video model; the last context-only image has no target Picture number. Multiple views of the same person do not request clones. Preserve all other explicit inclusions and exclusions. Output only the requested model prompt.'''


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


def _continuation_input(direction: str, reference_count: int, preserve_source_audio: bool) -> str:
    """Describe input roles in the user slot, never rewrite the authored guide.

    Only the caller's direction is subject to MAX_DIRECTION. This private
    envelope adds context without truncating the original words or pretending
    that a still frame supplies an observation of motion or audio.
    """
    roles = [f'<Picture {i}> is ordered reference {i}; use its identity or detail '
             'only for the requested change, not its reference-sheet background.'
             for i in range(1, reference_count + 1)]
    roles.append('The last attached image is the source scene context, '
                 'not a new actor/reference background. It is a frame of the saved '
                 'take being continued, not an additional character reference for H3. '
                 'It has no H3 Picture number. Describe the visible existing performers '
                 'and actual setting in words before applying the requested change; '
                 'never cite this context attachment as an H3 reference. '
                 'A reference sheet showing multiple views of the same individual '
                 'does not request duplicate performers.')
    audio = (
        'Preserve the source song and lyrics from <Audio 1>, the supplied source '
        'audio: continue its music, vocals, timing and performance with matching '
        'lip-sync; do not replace the song or invent lyrics.'
        if preserve_source_audio else
        'Maintain continuity of inherited music/song and voices; do not replace '
        'the soundtrack or invent lyrics. A still frame cannot reveal the audio; '
        'no audio reference is declared here.')
    return '\n'.join([
        'CONTINUATION of the saved source scene, not a new scene from a character sheet.',
        *roles,
        'Use the source frame as context for the existing casting, environment, '
        'visual style, lighting, framing and ongoing action. Keep all existing '
        'performers and their appearance unless the user explicitly changes them. '
        'Apply additional references only for the change requested by the user: '
        'this is not a new set or a blank-sheet composition. Do not replace the '
        'scene with a white/reference-sheet background or impose a new style. '
        'Do not invent actions or motion observations that the still frame cannot show.',
        audio,
        'Do not invent cuts, shot counts, timed transitions or a storyboard. '
        'Allow camera or shot changes only within the permission in the user '
        'direction; permission to change the shot is not a request for multiple cuts. '
        'Continue the inherited action and performance while applying that direction.',
        'Original user direction (preserve its complete meaning):',
        direction,
    ])


def build_prompt_graph(direction: str, references, *, mode: str = 'from-prompt',
                       clip_name: str | None = None,
                       filename_prefix: str = 'OpenGenjutsu/prompts/h3',
                       continuation_frame=None, preserve_source_audio=False) -> dict:
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
    if not isinstance(references, (list, tuple)) or (not references and continuation_frame is None):
        raise ValueError('At least one reference image is required')
    images = list(references)
    if continuation_frame is not None:
        # Qwen-only context follows the N unchanged references. Never mutate the
        # caller's list: H3 must still receive exactly its N character references.
        images.append(continuation_frame)
    graph = copy.deepcopy(json.loads(TEMPLATE.read_text()))

    # Root behavior stays unchanged. Only a real source frame enables the
    # continuation envelope; do not invent a visual observation when absent.
    graph[DIRECTION_NODE]['inputs']['string'] = (
        _continuation_input(direction, len(references), preserve_source_audio)
        if continuation_frame is not None else direction.strip())
    if continuation_frame is not None:
        graph[GENERATE_NODE]['inputs']['system_prompt'] = CONTINUATION_SYSTEM_PROMPT
    graph[MODE_NODE]['inputs']['choice'] = mode
    if clip_name is not None:
        if not isinstance(clip_name, str) or not _MODEL.fullmatch(clip_name):
            raise ValueError('clip_name must be a plain model filename')
        graph[CLIP_NODE]['inputs']['clip_name'] = clip_name
    graph[REFERENCE_NODE]['inputs']['image'] = _asset(images[0])

    # The installed ImageBatchMulti requires at least two images. With one
    # reference the same asset fills both slots; with several, each is attached.
    batch = graph[BATCH_NODE]['inputs']
    extra = images[1:]
    for position, asset in enumerate(extra, start=2):
        graph[f'{REFERENCE_NODE}_{position}'] = {
            'class_type': 'LoadImage', 'inputs': {'image': _asset(asset)}}
    batch['inputcount'] = max(2, len(images))
    batch['image_1'] = [REFERENCE_NODE, 0]
    batch['image_2'] = [f'{REFERENCE_NODE}_2', 0] if extra else [REFERENCE_NODE, 0]
    for position in range(3, len(images) + 1):
        batch[f'image_{position}'] = [f'{REFERENCE_NODE}_{position}', 0]
    for node in (*PREVIEW_NODES, *UNUSED_NODES):
        graph.pop(node, None)

    # The produced text is read back through a real SDK output, never a preview.
    graph[OUTPUT_NODE] = {'class_type': 'SaveText', 'inputs': {
        'text': [GENERATE_NODE, 0], 'format': 'txt',
        'filename_prefix': filename_prefix,
    }}
    return graph


_MEDIA_REFERENCE = re.compile(r'<\s*(Picture|Audio|Video)\s+([0-9]+)\s*>', re.IGNORECASE)
# Scan role prefixes, then distinguish a numbered tag from ordinary angle prose.
_MEDIA_REFERENCE_START = re.compile(r'<\s*(?:Picture|Audio|Video)', re.IGNORECASE)


def _looks_like_media_reference(text: str, end: int) -> bool:
    """Recognize an immediate digit after separators, or a bare closed role.

    Stop at words and angle brackets: <Picture frame 2> is prose, not a
    reference. Non-ASCII digits are ambiguous, not valid H3 indices.
    """
    i = end
    while i < len(text):
        char = text[i]
        if char.isdigit():
            return True
        if char == '>':
            return text[end:i].isspace() or i == end
        if char == '<' or char.isalnum() or char == '_':
            return False
        i += 1
    return False


def validate_continuation_prompt_references(text: str, reference_count: int, *,
                                            preserve_source_audio=False) -> str:
    """Close generated roles over actual H3 inputs; never rewrite model output.

    A Qwen-only context image is not an H3 Picture. Native pinning is not a
    supplied Video reference either. Reject ambiguity before any video sampling;
    do not silently substitute another role, truncate, or run a second refiner.
    """
    supplied = {'picture': range(1, reference_count + 1),
                'audio': (1,) if preserve_source_audio else (), 'video': ()}
    for start in _MEDIA_REFERENCE_START.finditer(text):
        if not _looks_like_media_reference(text, start.end()):
            continue
        match = _MEDIA_REFERENCE.match(text, start.start())
        if match is None:
            raise ValueError('The continuation prompt contains a malformed media reference. '
                             'Your take is unchanged.')
        role, index = match.group(1).lower(), int(match.group(2))
        if index not in supplied[role]:
            raise ValueError('The continuation prompt refers to inputs that were not supplied. '
                             'Your take is unchanged.')
    return text


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
