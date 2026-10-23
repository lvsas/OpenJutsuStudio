"""Compose the proven native chain into one service call.

restage the stored parent -> attest it -> compile -> freeze the intent -> submit
once -> download the published family -> register an immutable Take.

Every expensive or irreversible step happens after the cheap refusals: a Take that
cannot carry the pin window, or an incomplete model profile, is rejected before an
asset upload or a GPU submission.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from pathlib import Path

from continuable_take import get_take, get_validated_family, import_family, recover_imported_family
from continuity_jobs import create_operation, execute_operation
from h3_artifact_transport import download_h3_artifacts, revalidate_downloaded_h3_artifacts
from h3_continuity_graphs import H3ContinuityModels, NativeH3Parent, PIN_WINDOW
from h3_family_graphs import build_restage_graph, read_clip_handle
from h3_av_state import (AVStateError, UNCONTINUABLE_TAKE, require_continuable_child,
                         state_from_family, state_from_header, tail_fits)
from safetensor_header import read_safetensors_header
from h3_latent_graphs import PREFLIGHT_CLIP, build_latent_continuity
from readiness import missing_dependencies

FAMILY_NODE = 'native_family'
log = logging.getLogger(__name__)
RESTAGE_TIMEOUT = 900
FORWARD_TIMEOUT = 7200


class TargetMissingDependencies(ValueError):
    """The target cannot run the compiled continuation; nothing was sent."""

    def __init__(self, nodes=(), models=()):
        self.nodes = tuple(nodes)
        self.models = tuple(models)
        parts = []
        if self.models:
            parts.append('missing models or LoRAs: ' + ', '.join(self.models))
        if self.nodes:
            parts.append('missing nodes: ' + ', '.join(self.nodes))
        detail = '; '.join(parts) or 'the target inventory could not be validated'
        super().__init__('This compute target cannot run the continuation ('
                         + detail + '). The continuation was not submitted.')



def precheck_request(work, take_id, raw_frames):
    """Refuse a length whose take could not be continued, before any job exists."""
    state = state_from_family(get_validated_family(work, take_id))
    if state is not None:
        require_continuable_child(state, raw_frames)


def parent_context(artifacts):
    """The measured facts a parent must provide, checked before any upload."""
    # ``get_validated_family`` returns ValidatedTakeFamily, whose measured set is
    # ``.artifacts``; a bare H3ArtifactSet is also accepted so the unit doubles
    # keep exercising the same refusal path.
    family = getattr(artifacts, 'artifacts', artifacts)
    context = family.to_manifest()['context']
    delivered = context['delivered_frames']
    if delivered < PIN_WINDOW:
        raise ValueError(
            f'This take delivers {delivered / 24:.1f} s; extending needs at least {PIN_WINDOW / 24:.3f} s')
    if context['fps'] != 24:
        raise ValueError('Native continuation currently requires a 24 fps take')
    state = state_from_family(artifacts)
    if state is not None and not tail_fits(state):
        raise AVStateError(UNCONTINUABLE_TAKE)
    return context


def native_parent(take, artifacts, *, models, clip):
    """Build the attestation from measured facts, refusing an unusable parent.

    ``take`` is the frozen record, ``artifacts`` the freshly validated family and
    ``clip`` the loader literal the target returned after restaging. Nothing here
    trusts a filename convention or a caller-supplied geometry.
    """
    if not isinstance(models, H3ContinuityModels):
        raise ValueError('A complete continuity model profile is required')
    context = parent_context(artifacts)
    return NativeH3Parent(take_id=take.take_id, clip=clip, width=context['width'],
                          height=context['height'],
                          delivered_frames=context['delivered_frames'], fps=24,
                          models=models, capsule_digest=take.capsule_sha256)


def parent_from_registry(work: str | Path, take_id: str, *, models, clip):
    """Re-validate the stored family, then build the parent attestation."""
    return native_parent(get_take(work, take_id), get_validated_family(work, take_id),
                         models=models, clip=clip)


def restage_parent(client, artifacts, family_name):
    """Upload immutable copies with unique requested names through the SDK.

    Names are hints, not resolved target paths: content-addressed SDK/proxy dedup
    can reuse an existing upload (including ComfyUI's collision counter). The
    restager and shared validator must both accept those actual names.
    """
    sources = (('video', artifacts.video, '.mp4'),
               ('mctx', artifacts.mctx, '.mctx.safetensors'),
               ('conditioning', artifacts.conditioning, '.cond.safetensors'))
    with tempfile.TemporaryDirectory(prefix='restage-') as staging:
        references = {}
        for role, path, suffix in sources:
            # Copy rather than rename: the stored family stays untouched.
            unique = Path(staging) / f'{family_name}{suffix}'
            unique.write_bytes(Path(path).read_bytes())
            references[role] = client.assets.from_file(unique).as_reference()
        # Log only requested basenames, not opaque ids or local/private paths.
        # They are hints: resolved ComfyUI inputs must be read from job history.
        log.info('restaging %s with requested upload names %s', family_name,
                 [f'{family_name}{suffix}' for _, _, suffix in sources])
        job = client.run(client.workflows.from_json(build_restage_graph(references, family_name)),
                         timeout=RESTAGE_TIMEOUT)
    if getattr(job, 'status', None) != 'succeeded':
        raise ValueError('The parent family could not be restaged on the target')
    return read_clip_handle(job, family_name)


def _carry_reference(source: Path, target: Path) -> None:
    """Expose only a complete copy; never overwrite a retained final reference."""
    data = source.read_bytes()

    def check_existing():
        if target.is_symlink() or target.read_bytes() != data:
            raise ValueError('A retained reference differs from this native collection')

    if os.path.lexists(target):
        check_existing()
        return
    staging = target.with_name(f'.{target.name}.{uuid.uuid4().hex}.part')
    try:
        with staging.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staging, target, follow_symlinks=False)
        except FileExistsError:
            check_existing()
        descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        staging.unlink(missing_ok=True)  # Only this invocation's private temporary.


def collect_forward(work: str | Path, folder: Path, *, compiled_graph,
                    reference_path: str | Path | None = None,
                    reference_paths=None, operator_label='native-forward', expected_state=None):
    """Return the collector ``execute_operation`` expects, idempotent by Take id."""
    # Absolute, because the source-root confinement compares resolved paths and a
    # relative root made every freshly downloaded artifact look like an escape.
    folder = Path(folder).absolute()
    # An explicit sequence, even empty, wins over the historical singular input.
    paths = tuple(reference_paths) if reference_paths is not None else (
        (reference_path,) if reference_path is not None else ())

    def collect(remote_job, intent, operation_id):
        published = recover_imported_family(work, operation_id, captured_graph=compiled_graph,
            source_job=remote_job.id, operator_label=operator_label)
        if published is not None:
            if expected_state is not None and state_from_family(published) != expected_state:
                raise ValueError('The published Take differs from the validated native timing')
            return published.record.take_id
        if os.path.lexists(folder):
            revalidate_downloaded_h3_artifacts(remote_job, FAMILY_NODE, folder)
        else:
            download_h3_artifacts(remote_job, FAMILY_NODE, folder)
        if expected_state is not None:
            with (folder / 'take.mctx.safetensors').open('rb') as stream:
                actual_state = state_from_header(read_safetensors_header(stream))
            if actual_state != expected_state:
                raise ValueError('The generated timing differs from the validated native operation. '
                                 'The output was kept but was not registered as a continuable take.')
        # Parent/context images live outside this import root. Copy every image
        # into it, in prompt order, before applying import_family's confinement.
        carried = []
        for index, reference in enumerate(paths, start=1):
            source = Path(reference)
            target = folder / f'reference-{index}{source.suffix.lower()}'
            _carry_reference(source, target)
            carried.append(target)
        record = import_family(
            folder / 'take.mp4', folder / 'take.mctx.safetensors',
            folder / 'take.cond.safetensors', root=folder, work=work,
            captured_graph=compiled_graph, take_id=operation_id,
            graph_completeness='complete', graph_source='operator_capture',
            source_job=remote_job.id, operator_label=operator_label,
            references=tuple(carried))
        return record.take_id
    return collect


def _anchor_ids(mode, parent_ids):
    if (mode not in ('forward', 'prepend', 'bridge') or not isinstance(parent_ids, tuple)
            or len(parent_ids) != (2 if mode == 'bridge' else 1)
            or any(not isinstance(id, str) or not re.fullmatch(r'[0-9a-f]{32}', id) for id in parent_ids)
            or len(set(parent_ids)) != len(parent_ids)):
        raise ValueError('The native operation needs distinct, explicitly ordered saved takes.')


def _checked_anchors(work, parent_ids, raw_frames, mode):
    """One pure refusal boundary shared by preflight and submission, before uploads."""
    _anchor_ids(mode, parent_ids)
    families = tuple(get_validated_family(work, id) for id in parent_ids)
    plan = None
    if mode == 'forward':
        contexts = (parent_context(families[0]),)
        state = state_from_family(families[0])
        if state is not None:
            require_continuable_child(state, raw_frames)
    else:
        from h3_native_boundaries import prepare_operation
        contexts = tuple(family.artifacts.to_manifest()['context'] for family in families)
        if any((c['width'], c['height'], c['fps']) !=
               (contexts[0]['width'], contexts[0]['height'], 24) for c in contexts):
            raise ValueError('These anchors need matching picture sizes and 24 fps timing.')
        identities = tuple(c.get('self_id') for c in contexts)
        if any(not identity for identity in identities) or len(set(identities)) != len(identities):
            raise ValueError('These anchors must name distinct verified native sources.')
        states = []
        for family in families:
            state = state_from_family(family)
            if state is None:
                raise ValueError('The saved timing could not be checked. Nothing was submitted.')
            states.append(state)
        plan = prepare_operation(mode, tuple(states), raw_frames)
    return families, contexts, plan


def preflight_continuation(work, take_id, *, models, direction, reference_count,
                           raw_frames=277, inventory=None, mode='forward', second_take_id=None):
    """Read-only dependency gate before reference upload or prompt refinement.

    Sentinel assets and parent handle are used only for compiling node/model
    inventory, never submitted. Both authored graphs are inspected separately so
    node identifiers cannot collide. This does not claim runtime validation of
    bundle-fed settings or remote asset availability.
    """
    from h3_prompt_generator import build_prompt_graph
    if type(reference_count) is not int or reference_count < 1:
        raise ValueError('At least one reference image is required for continuation.')
    parent_ids = (take_id,) if second_take_id is None else (take_id, second_take_id)
    _, contexts, _ = _checked_anchors(work, parent_ids, raw_frames, mode)
    context = contexts[0]
    refs = [{'__type': 'core/ASSET', 'info': {'id': f'preflight-reference-{i}'}}
            for i in range(reference_count)]
    graph = build_latent_continuity(
        references=refs, prompt=direction, width=context['width'], height=context['height'],
        raw_frames=raw_frames, seed=0, models=models, parent_clip=PREFLIGHT_CLIP,
        operation_id='f' * 32, publish_family=True, mode=mode,
        second_parent_clip='preflight/second-not-real.mp4' if mode == 'bridge' else None)
    probe = inventory or missing_dependencies
    nodes, weights = set(), set()
    for candidate in (graph, build_prompt_graph(direction, refs)):
        absent_nodes, absent_weights = probe(candidate)
        nodes.update(absent_nodes); weights.update(absent_weights)
    if nodes or weights:
        raise TargetMissingDependencies(sorted(nodes), sorted(weights))


def submit_forward(work: str | Path, take_id: str, request, **options):
    """Compatibility entry point: existing Forward callers use the shared service."""
    return submit_continuation(work, (take_id,), request, mode='forward', **options)


def submit_continuation(work: str | Path, parent_ids: tuple[str, ...], request, *,
                   mode: str, client, models, references, target_fingerprint, work_root: str | Path,
                   reference_path: str | Path | None = None,
                   reference_paths=None,
                   operation_id: str | None = None,
                   inventory=missing_dependencies):
    """One SDK chain for explicit native anchors; routes are separately gated.

    ``request`` carries an effective prompt, explicit seed and native frame count.
    Parent IDs are trusted validated intent, never clip paths. The same restage,
    checkpoint, execute and collector lifecycle serves every anchored mode.

    ``inventory`` answers ``(missing_nodes, missing_models)`` for a compiled graph.
    It runs before the parent upload so a target that cannot run the graph costs
    nothing; a target that cannot be inspected refuses too, rather than queueing a
    graph the host may reject.
    """
    operation_id = operation_id or uuid.uuid4().hex
    families, contexts, plan = _checked_anchors(work, parent_ids, request.raw_frames, mode)
    context = contexts[0]

    def compile_graph(clips):
        return build_latent_continuity(
            references=list(references), prompt=request.prompt,
            width=context['width'], height=context['height'],
            raw_frames=request.raw_frames, seed=request.seed, models=models,
            parent_clip=clips[0], operation_id=operation_id, publish_family=True,
            mode=mode, second_parent_clip=clips[1] if mode == 'bridge' else None)

    # The graph's installable dependencies do not depend on the parent handle, so
    # the target is asked before the restage upload rather than after it.
    sentinels = (PREFLIGHT_CLIP, 'preflight/second-not-real.mp4')[:len(parent_ids)]
    missing_nodes, missing_models = inventory(compile_graph(sentinels))
    if missing_nodes or missing_models:
        raise TargetMissingDependencies(missing_nodes, missing_models)

    clips = tuple(restage_parent(client, family, uuid.uuid4().hex) for family in families)
    if mode == 'forward':
        # Preserve the historical attestation path and its profile guard.
        native_parent(get_take(work, parent_ids[0]), families[0], models=models, clip=clips[0])
    compiled = compile_graph(clips)

    create_operation(work_root, operation_id, mode=mode, graph=compiled,
                     seed=request.seed, parents=parent_ids,
                     target_fingerprint=target_fingerprint)
    folder = Path(work) / 'media' / f'{mode}-{operation_id}'
    labels = {'operator_label': 'native-' + mode, 'expected_state': plan.child} if plan is not None else {}
    collect = collect_forward(work, folder, compiled_graph=compiled,
                              reference_path=reference_path,
                              reference_paths=reference_paths, **labels)
    return execute_operation(work_root, operation_id, client,
                             target_fingerprint=target_fingerprint, collect=collect,
                             timeout=FORWARD_TIMEOUT)
