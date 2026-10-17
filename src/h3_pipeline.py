"""Isolated H3 worker: official SDK assets → graph → MP4 → frozen capsule.

Only supports single-shot inputs. Never calls the LTX engine registry or cancels
other jobs. Dispatch this function in the application's normal worker queue.
"""
import copy
import time
from pathlib import Path
import core
from comfy_transport import make_client
from h3_media import prepare_source, finish_result, validate_result, has_audio
from h3_capsule import contained, digest_file, freeze_capsule
from h3_preserve import describe_preserved
from h3_recipe import ENGINE, bind_frames, validate_recipe, with_preserve_clip
from media import ffprobe


def _complete_preserve_clip(client, recipe, prepared, folder):
    """Ask the local vision model what the clip must keep, before the graph is frozen.

    Returns the completed recipe and, when the model was unavailable or produced
    something unusable, a warning recorded on the job. A failed description does not
    fail the render: it leaves the recipe without preservation text, which is the
    weakest configuration, and says so instead of hiding it.
    """
    if recipe.get('preserve_clip_source') != 'none':
        return recipe, None
    try:
        described = describe_preserved(client, prepared, folder / 'preserve')
    except Exception as exc:
        return recipe, f'Clip preservation was not described ({type(exc).__name__}); the swap may be less faithful.'
    return with_preserve_clip(recipe, described['text'], 'generated'), None


def _download_mp4(client, graph, folder):
    workflow = client.workflows.from_json(graph)
    remote = client.run(workflow, timeout=1800)
    outputs = remote.get_outputs('156')
    output = next((item for item in outputs if Path(str(item.name)).suffix.lower() == '.mp4'), None)
    if output is None:
        raise RuntimeError('H3 node 156 returned no MP4 artifact')
    destination = folder / 'download.mp4'
    partial = folder / 'download.mp4.part'
    try:
        output.to_file(partial)
        if not partial.is_file() or not partial.stat().st_size:
            raise RuntimeError('H3 MP4 download was empty')
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def run_h3_pipeline(job, video_path, opts):
    """Worker signature compatible with dispatch(job, video_path, opts).

    opts: recipe, reference_image, media_dir (optional; defaults WORK/media),
    input_hashes (optional). On replay recipe is used verbatim, not recompiled.
    """
    client = None
    job.status, job.started, job.finished = 'running', time.time(), None
    job.step, job.progress, job.result, job.error = 'h3_prepare', 0.02, None, None
    job.meta.pop('h3_capsule', None)
    job.save()
    try:
        if job.engine != ENGINE:
            raise ValueError('H3 runner accepts only minimax-h3 jobs')
        media_dir = Path(opts.get('media_dir', core.WORK / 'media')).resolve()
        source = contained(video_path, media_dir)
        reference = contained(opts['reference_image'], media_dir)
        recipe = validate_recipe(copy.deepcopy(opts['recipe']))
        input_hashes = {role: digest_file(path) for role, path in
                        [('source', source), ('reference', reference)]}
        for role, path in [('source', source), ('reference', reference)]:
            expected = opts.get('input_hashes', {}).get(role)
            if expected and input_hashes[role] != expected:
                raise ValueError('An H3 queued input changed')
        folder = media_dir / f'h3-{job.id}'
        # Job.path performs identifier validation before any output directory creation.
        job.path
        folder.mkdir(parents=True, exist_ok=False)
        prepared, count, padded = prepare_source(source, folder)
        prepared_audio = has_audio(prepared)
        if recipe['source_frames_24fps'] is not None and recipe.get('source_audio') is not None \
                and recipe['source_audio'] is not prepared_audio:
            raise ValueError('Replay conditioning audio differs from the frozen recipe')
        if recipe['source_frames_24fps'] not in (None, count):
            raise ValueError('Replay normalization differs from the frozen recipe')
        client = make_client()
        if recipe['source_frames_24fps'] is None:
            recipe, preserve_warning = _complete_preserve_clip(client, recipe, prepared, folder)
            if preserve_warning:
                job.meta['h3_preserve_warning'] = preserve_warning
            recipe = bind_frames(recipe, count, source_audio=prepared_audio)
        if recipe['inference_frames'] != padded:
            raise ValueError('H3 preprocessing frame grid differs from the recipe')
        validate_recipe(recipe)
        job.prompt = recipe['effective_prompt']
        job.video = str(source)
        job.meta.update(h3_reference=str(reference), h3_recipe=copy.deepcopy(recipe),
                        source_frames=count, processed_frames=count, fps=24,
                        shot_plan=copy.deepcopy(recipe['shot_plan']),
                        padding_frames=padded-count, single_shot_only=True)
        job.step, job.progress = 'h3_submitting', 0.15
        job.save()
        video_ref = client.assets.from_file(prepared).as_reference()
        image_ref = client.assets.from_file(reference).as_reference()
        # The prepared clip keeps its soundtrack so the reference node and the
        # combine node both condition on it, matching the measured winning arm.
        graph = copy.deepcopy(recipe['graph_template'])
        graph['155']['inputs']['video'] = video_ref
        graph['137']['inputs']['image'] = image_ref
        graph['156']['inputs']['filename_prefix'] = f'OpenGenjutsu/h3-{job.id}'
        rendered = _download_mp4(client, graph, folder)
        if ffprobe(rendered)['frames'] < count:
            raise ValueError('H3 inference returned fewer than the source frames')
        job.step, job.progress = 'h3_assemble', 0.9
        job.save()
        result = finish_result(rendered, source, folder / 'result.mp4', count)
        validate_result(result, count, recipe['output_width'], recipe['output_height'])
        if any(digest_file(path) != input_hashes[role] for role, path in
               [('source', source), ('reference', reference)]):
            raise ValueError('An H3 input changed during rendering')
        freeze_capsule(job, recipe, source, reference, result, media_dir)
        job.result, job.status, job.step, job.progress = str(result.resolve()), 'done', 'done', 1.0
    except Exception as exc:
        job.status, job.step = 'error', 'h3_error'
        job.error = f'{type(exc).__name__}: {exc}'
        job.result = None
        job.meta.pop('h3_capsule', None)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass  # Cleanup must not suppress terminal persistence.
        job.finished = time.time()
        job.save()
