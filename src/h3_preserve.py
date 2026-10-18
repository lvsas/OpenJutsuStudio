"""Name what must be preserved in a source clip, from the clip itself.

The text is produced from frames of the source, so it can only name what is actually
visible. It is deliberately narrow: no actions, no camera movement, no shot list, no
timings. That is the failure mode measured in the rejected R2VA refiner, which produced
plausible prose about a clip it could not see — the H3 text encoder has no vision, so
this path uses a real vision node instead.

Written with SaveText rather than PreviewAny: text nodes return nothing through the
official SDK, while a saved file comes back as a downloadable output on any target.
"""
import subprocess
from pathlib import Path
from media import ffprobe

FRAME_COUNT = 4
VISION_NODE = 'AILab_QwenVL'
SAVE_NODE = 'SaveText'
VISION_MODEL = 'Qwen3-VL-2B-Instruct'
VISION_QUANTIZATION = '4-bit (VRAM-friendly)'
MAX_TEXT = 400
FORBIDDEN = ('[shot', 'at 00:', '<d>', 'shot 1', 'scene 1')

INSTRUCTION = (
    'These are frames from one short video clip. One person in the clip will be replaced by a '
    'different character and everything else must stay as it is. List only the visible things '
    'that must remain unchanged: objects the person holds or touches, clothing or accessories '
    'that cover them, and the setting they are in. Answer with one short English sentence '
    'listing those elements. Do not describe actions, camera movement, shot lists or timings.'
)

CHARACTER_INSTRUCTION = (
    'This is a character reference. Describe only the person\'s own appearance, as a short '
    'phrase that could replace a character description: body build, hair and what they wear. '
    'Do not mention poses, actions, props, animals, other people, the background, the image '
    'layout or the image style. Answer with one short English sentence.'
)


def validate_preserved(text):
    """Accept one short visible-content sentence, refuse anything else."""
    if not isinstance(text, str):
        raise ValueError('Preserved description must be text')
    cleaned = ' '.join(text.split())
    if not cleaned:
        raise ValueError('Preserved description is empty')
    if len(cleaned) > MAX_TEXT:
        raise ValueError('Preserved description is too long')
    lowered = cleaned.lower()
    if any(marker in lowered for marker in FORBIDDEN):
        raise ValueError('Preserved description describes the edit instead of the clip')
    return cleaned


def frame_indices(total, count=FRAME_COUNT):
    """Evenly spaced indices, always including the first frame."""
    if type(total) is not int or total < 1 or type(count) is not int or count < 1:
        raise ValueError('Frame sampling needs a positive frame count')
    if total <= count:
        return list(range(total))
    step = (total - 1) / (count - 1) if count > 1 else 0
    return sorted({int(round(index * step)) for index in range(count)})


def sample_frames(video, folder, count=FRAME_COUNT):
    """Write one PNG per sampled frame and return them in order."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    indices = frame_indices(ffprobe(video)['frames'], count)
    frames = []
    for position, index in enumerate(indices):
        destination = folder / f'preserve-{position:02d}.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-vf',
                        f'select=eq(n\\,{index})', '-frames:v', '1', str(destination)],
                       check=True, timeout=120)
        if not destination.is_file() or not destination.stat().st_size:
            raise ValueError('Frame sampling produced no image')
        frames.append(destination)
    return frames


def build_preserve_graph(frames, *, model=VISION_MODEL, quantization=VISION_QUANTIZATION,
                         instruction=INSTRUCTION, filename_prefix='opengenjutsu/preserve'):
    """API-format graph: frame assets -> local vision node -> saved text file.

    A single image is wired straight into the vision node: ImageBatchMulti requires at
    least two inputs, and one reference image is the normal character case.
    """
    if not frames:
        raise ValueError('Preserved description needs at least one frame')
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError('Preserved description needs a non-empty instruction')
    graph = {}
    if len(frames) == 1:
        graph['30'] = {'class_type': 'LoadImage', 'inputs': {'image': frames[0]}}
        image_source = ['30', 0]
    else:
        image_inputs = {}
        for position, frame in enumerate(frames):
            node_id = str(30 + position)
            graph[node_id] = {'class_type': 'LoadImage', 'inputs': {'image': frame}}
            image_inputs[f'image_{position + 1}'] = [node_id, 0]
        graph['10'] = {'class_type': 'ImageBatchMulti',
                       'inputs': {'inputcount': len(frames), **image_inputs}}
        image_source = ['10', 0]
    graph['40'] = {'class_type': VISION_NODE, 'inputs': {
        'model_name': model, 'quantization': quantization, 'attention_mode': 'auto',
        'preset_prompt': '🖼️ Simple Description', 'custom_prompt': instruction,
        'max_tokens': 512, 'keep_model_loaded': True, 'seed': 1, 'image': image_source}}
    graph['50'] = {'class_type': SAVE_NODE, 'inputs': {
        'text': ['40', 0], 'filename_prefix': filename_prefix, 'format': 'txt'}}
    return graph


def _saved_text(job):
    for output in job.outputs or []:
        name = str(getattr(output, 'name', ''))
        content_type = str(getattr(output, 'content_type', ''))
        if name.endswith('.txt') or content_type.startswith('text/'):
            return output.to_bytes().decode('utf-8', 'replace')
    raise RuntimeError('The vision node returned no readable text output')


def describe_preserved(client, source, folder, *, count=FRAME_COUNT, model=VISION_MODEL,
                       quantization=VISION_QUANTIZATION, instruction=INSTRUCTION, timeout=1200):
    """Sample the clip, ask the local vision model, return one validated sentence."""
    frames = sample_frames(source, folder, count)
    assets = [client.assets.from_file(frame).as_reference() for frame in frames]
    graph = build_preserve_graph(assets, model=model, quantization=quantization,
                                 instruction=instruction)
    job = client.submit(client.workflows.from_json(graph))
    job.wait(timeout=timeout)
    text = validate_preserved(_saved_text(job))
    return {'text': text, 'model': model, 'frames': len(frames), 'job_id': str(job.id)}


def describe_character(client, reference, *, model=VISION_MODEL,
                       quantization=VISION_QUANTIZATION, timeout=1200):
    """Describe the replacement character from its reference image alone.

    Same mechanism as the clip description, one image instead of a sampled clip: the text
    can only name what is visible in the reference the operator actually supplied.
    """
    asset = client.assets.from_file(reference).as_reference()
    graph = build_preserve_graph([asset], model=model, quantization=quantization,
                                 instruction=CHARACTER_INSTRUCTION,
                                 filename_prefix='opengenjutsu/character')
    job = client.submit(client.workflows.from_json(graph))
    job.wait(timeout=timeout)
    text = validate_preserved(_saved_text(job))
    return {'text': text, 'model': model, 'frames': 1, 'job_id': str(job.id)}
