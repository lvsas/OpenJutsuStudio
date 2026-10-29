"""Isolated H3 worker: official SDK assets → graph → MP4 → frozen capsule.

Only supports single-shot inputs. Never calls the LTX engine registry or cancels
other jobs. Dispatch this function in the application's normal worker queue.
"""
import copy
import hashlib
import os
import time
from dataclasses import asdict
from pathlib import Path
import core
from comfy_transport import make_client
from continuable_take import import_family, recover_imported_family
from h3_artifact_transport import download_h3_artifacts, revalidate_downloaded_h3_artifacts
from h3_continuity_graphs import Weight
from h3_graphs import H3Models, REFERENCE_NODE
from h3_swap_native import build_swap_native_capture, native_inventory_graph, NATIVE_ARTIFACT_RELATION
from continuity_pipeline import _carry_reference
from readiness import missing_dependencies
from h3_media import prepare_source, finish_result, validate_result, has_audio
from h3_capsule import contained, digest_file, freeze_capsule
from h3_preserve import describe_character, describe_preserved
from h3_recipe import ENGINE, bind_frames, validate_recipe, with_preserve_clip, with_reference_description
from media import ffprobe
from source_clip import require_short_source

# The node pack publishes the MP4/MCTX/COND triplet on this SDK output node.
NATIVE_FAMILY_NODE = 'native_swap_family'


def _reference_paths(opts):
    """Queued reference paths, newest key first with the historical single key after."""
    recorded = opts.get('reference_images')
    if recorded:
        return list(recorded)
    single = opts.get('reference_image')
    return [single] if single else []


def _complete_reference_descriptions(client, recipe, references, folder):
    """Name each replacement character from its own reference image.

    Called before the graph is frozen so the frozen template and the capsule both carry the
    text and its provenance. An operator's own description is never sent to the model and
    never overwritten; a reference the model cannot describe is left empty and reported.
    """
    updated = recipe
    warnings = []
    for index, reference in enumerate(references):
        if updated['reference_descriptions'][index].strip():
            continue
        try:
            described = describe_character(client, reference)
        except Exception as exc:
            warnings.append(f'Character {index + 1} was not described ({type(exc).__name__}).')
            continue
        updated = with_reference_description(updated, index, described['text'], 'generated')
    return updated, ' '.join(warnings) or None


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


def native_operation_id(job):
    """Deterministic server-side identity for one Swap's native capture.

    Derived from the job, so a retried collection reuses the same Take instead of
    publishing a second one. It is not a client-supplied value.
    """
    return hashlib.sha256(f'opengenjutsu-native-swap:{job.id}'.encode('utf-8')).hexdigest()[:32]


def _weight_profile(opts, recipe):
    """Which weights are used — by filename, with a byte hash only if one exists.

    The target resolves identity by filename; nobody can hash tens of gigabytes on
    a hosted machine, so a measured hash is an optional enrichment, never a
    prerequisite. The captured record states which of the two it holds.
    """
    raw = opts.get('weights')
    if raw is None:
        return {role: Weight(name) for role, name in recipe['model_files'].items()}
    if not isinstance(raw, dict) or set(raw) != set(asdict(H3Models())):
        raise ValueError('A supplied weight profile must name every effective role')
    profile = {}
    for role, value in raw.items():
        if not isinstance(value, dict) or not isinstance(value.get('filename'), str):
            raise ValueError('A weight profile entry must name its file')
        digest = value.get('sha256')
        if digest is not None and not isinstance(digest, str):
            raise ValueError('A measured weight hash must be a string')
        profile[role] = Weight(value['filename'], digest)
    return profile


def _submit(client, graph):
    """Exactly one SDK submission. Every output is read from the returned job."""
    return client.run(client.workflows.from_json(graph), timeout=1800)


def _published_mp4(remote, folder):
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


def _publish_native_take(job, remote, folder, media_dir, graph, *, references=()):
    """Collect once, carry reference bytes, and reuse only a revalidated matching Take."""
    take_id = native_operation_id(job)
    def recovered():
        return recover_imported_family(core.WORK, take_id, captured_graph=graph,
                                       source_job=job.id, operator_label='native-swap')
    published = recovered()
    if published is not None:
        return published.record.take_id
    destination = folder / 'native'
    if os.path.lexists(destination):
        revalidate_downloaded_h3_artifacts(remote, NATIVE_FAMILY_NODE, destination)
    else:
        download_h3_artifacts(remote, NATIVE_FAMILY_NODE, destination)
    carried = []
    for index, reference in enumerate(references, start=1):
        source = Path(reference)
        target = destination / f'reference-{index}{source.suffix.lower()}'
        _carry_reference(source, target)
        carried.append(target)
    try:
        record = import_family(
            destination / 'take.mp4', destination / 'take.mctx.safetensors',
            destination / 'take.cond.safetensors', root=destination, work=core.WORK,
            captured_graph=graph, take_id=take_id, graph_completeness='complete',
            graph_source='operator_capture', source_job=job.id,
            operator_label='native-swap', references=carried)
    except FileExistsError:
        published = recovered()
        if published is None:
            raise ValueError('Native Take publication could not be confirmed') from None
        return published.record.take_id
    return record.take_id


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
        if opts.get('native_capture', True) is not True:
            raise ValueError('Every H3 generation must save its complete continuation state.')
        media_dir = Path(opts.get('media_dir', core.WORK / 'media')).resolve()
        source = contained(video_path, media_dir)
        source_info = require_short_source(source)
        references = [contained(path, media_dir) for path in _reference_paths(opts)]
        recipe = validate_recipe(copy.deepcopy(opts['recipe']))
        if len(references) != recipe['reference_count']:
            raise ValueError('H3 queued references do not match the frozen recipe')
        inputs = [('source', source),
                  *[(f'reference-{index}', path) for index, path in enumerate(references)]]
        input_hashes = {role: digest_file(path) for role, path in inputs}
        for role, path in inputs:
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
        preview = (bind_frames(recipe, count, source_audio=prepared_audio)
                   if recipe['source_frames_24fps'] is None else recipe)
        graph = native_inventory_graph(preview, operation_id=native_operation_id(job),
                                       weights=_weight_profile(opts, preview))
        try:
            missing_nodes, missing_models = missing_dependencies(graph)
        except Exception:
            raise ValueError('Native state inventory could not be verified. No inference was submitted.') from None
        if missing_nodes or missing_models:
            raise ValueError('Native state dependencies are unavailable. No inference was submitted.')
        client = make_client()
        if recipe['source_frames_24fps'] is None:
            recipe, reference_warning = _complete_reference_descriptions(
                client, recipe, references, folder)
            if reference_warning:
                job.meta['h3_reference_warning'] = reference_warning
            recipe, preserve_warning = _complete_preserve_clip(client, recipe, prepared, folder)
            if preserve_warning:
                job.meta['h3_preserve_warning'] = preserve_warning
            recipe = bind_frames(recipe, count, source_audio=prepared_audio)
        if recipe['inference_frames'] != padded:
            raise ValueError('H3 preprocessing frame grid differs from the recipe')
        validate_recipe(recipe)
        job.prompt = recipe['effective_prompt']
        job.video = str(source)
        job.meta.update(h3_references=[str(path) for path in references],
                        h3_recipe=copy.deepcopy(recipe),
                        source_info=copy.deepcopy(source_info),
                        source_shot_plan=[{'start': 0, 'end': source_info['frames']-1,
                                           'fps': source_info['fps']}],
                        source_frames=count, processed_frames=count, fps=24,
                        shot_plan=copy.deepcopy(recipe['shot_plan']),
                        padding_frames=padded-count, single_shot_only=True)
        job.step, job.progress = 'h3_submitting', 0.15
        job.save()
        video_ref = client.assets.from_file(prepared).as_reference()
        image_refs = [client.assets.from_file(path).as_reference() for path in references]
        # The prepared clip keeps its soundtrack so the reference node and the
        # combine node both condition on it, matching the measured winning arm.
        graph = copy.deepcopy(recipe['graph_template'])
        graph['155']['inputs']['video'] = video_ref
        for index, image_ref in enumerate(image_refs):
            graph[str(REFERENCE_NODE + index)]['inputs']['image'] = image_ref
        # One sampling job publishes the display result and complete continuation state.
        operation_id = native_operation_id(job)
        graph['156']['inputs']['filename_prefix'] = f'OpenGenjutsu/h3-{operation_id}'
        capture = build_swap_native_capture(
            recipe, graph, operation_id=operation_id,
            weights=_weight_profile(opts, recipe), publish_family=True)
        submitted = capture.graph
        job.meta['native_capture_digest'] = capture.digest
        remote = _submit(client, submitted)
        rendered = _published_mp4(remote, folder)
        if ffprobe(rendered)['frames'] < count:
            raise ValueError('H3 inference returned fewer than the source frames')
        job.step, job.progress = 'h3_assemble', 0.9
        job.save()
        result = finish_result(rendered, source, folder / 'result.mp4', count)
        validate_result(result, count, recipe['output_width'], recipe['output_height'])
        if any(digest_file(path) != input_hashes[role] for role, path in inputs):
            raise ValueError('An H3 input changed during rendering')
        freeze_capsule(job, recipe, source, references, result, media_dir)
        job.meta['native_take_id'] = _publish_native_take(
            job, remote, folder, media_dir, submitted, references=references)
        job.meta['native_artifact_relation'] = NATIVE_ARTIFACT_RELATION
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