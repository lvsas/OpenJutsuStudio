"""Compose the proven native chain into one service call.

restage the stored parent -> attest it -> compile -> freeze the intent -> submit
once -> download the published family -> register an immutable Take.

Every expensive or irreversible step happens after the cheap refusals: a Take that
cannot carry the pin window, or an incomplete model profile, is rejected before an
asset upload or a GPU submission.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from continuable_take import get_take, get_validated_family, import_family
from continuity_jobs import create_operation, execute_operation
from h3_artifact_transport import download_h3_artifacts
from h3_continuity_graphs import (H3ContinuityModels, NativeH3Parent, PIN_WINDOW,
                                  build_h3_continuity)
from h3_family_graphs import build_restage_graph, read_clip_handle

FAMILY_NODE = 'native_family'
RESTAGE_TIMEOUT = 900
FORWARD_TIMEOUT = 7200
# Calliope's working full-latent forward uses ramp 0 / edge 0 / hold 0 with the
# parent latent concatenated. The ramp is kept as a parameter, but matching the
# proven recipe matters more than tuning a symptom of the missing concat.
PIN_RAMP_FRAMES = 0
PIN_RAMP_EDGE = 0.0


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
            f'This take delivers {delivered} frames; a tail pin needs at least {PIN_WINDOW}')
    if context['fps'] != 24:
        raise ValueError('Native continuation currently requires a 24 fps take')
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
    """Upload the three files and let the installed pack rebuild a loadable family."""
    references = {role: client.assets.from_file(path).as_reference()
                  for role, path in (('video', artifacts.video), ('mctx', artifacts.mctx),
                                     ('conditioning', artifacts.conditioning))}
    job = client.run(client.workflows.from_json(build_restage_graph(references, family_name)),
                     timeout=RESTAGE_TIMEOUT)
    if getattr(job, 'status', None) != 'succeeded':
        raise ValueError('The parent family could not be restaged on the target')
    return read_clip_handle(job, family_name)


def collect_forward(work: str | Path, folder: Path, *, compiled_graph,
                    reference_path: str | Path | None = None):
    """Return the collector ``execute_operation`` expects, idempotent by Take id."""
    # Absolute, because the source-root confinement compares resolved paths and a
    # relative root made every freshly downloaded artifact look like an escape.
    folder = Path(folder).resolve()

    def collect(remote_job, intent, operation_id):
        download_h3_artifacts(remote_job, FAMILY_NODE, folder)
        # The reference comes from the parent take, which is outside this import
        # root by construction. Bring it into the folder first, so the take can
        # carry it and the source-root confinement still means something.
        carried = ()
        if reference_path is not None:
            suffix = Path(reference_path).suffix.lower()
            target = folder / f'reference-1{suffix}'
            target.write_bytes(Path(reference_path).read_bytes())
            carried = (target,)
        record = import_family(
            folder / 'take.mp4', folder / 'take.mctx.safetensors',
            folder / 'take.cond.safetensors', root=folder, work=work,
            captured_graph=compiled_graph, take_id=operation_id,
            graph_completeness='complete', graph_source='operator_capture',
            source_job=remote_job.id, operator_label='native-forward',
            references=carried)
        return record.take_id
    return collect


def submit_forward(work: str | Path, take_id: str, request, *, client, models,
                   reference, target_fingerprint, work_root: str | Path,
                   reference_path: str | Path | None = None,
                   operation_id: str | None = None):
    """Run the whole chain for one Forward request and return the operation view.

    ``request`` is a validated ``ForwardRequest``: prompt, explicit seed and native
    frame count only. The parent comes from the URL, the graph from the compiler,
    and the operation identity from the service.
    """
    operation_id = operation_id or uuid.uuid4().hex
    artifacts = get_validated_family(work, take_id)
    context = parent_context(artifacts)  # refuse before any upload

    family_name = uuid.uuid4().hex
    clip = restage_parent(client, artifacts, family_name)
    parent = native_parent(get_take(work, take_id), artifacts, models=models, clip=clip)

    compiled = build_h3_continuity(
        'forward', reference, request.prompt, operation_id=operation_id,
        seed=request.seed, width=context['width'], height=context['height'],
        raw_frames=request.raw_frames, models=models, parents=(parent,),
        publish_family=True, ramp_frames=PIN_RAMP_FRAMES, ramp_edge=PIN_RAMP_EDGE)

    create_operation(work_root, operation_id, mode='forward', graph=compiled.graph,
                     seed=request.seed, parents=(take_id,),
                     target_fingerprint=target_fingerprint)
    folder = Path(work) / 'media' / f'forward-{operation_id}'
    collect = collect_forward(work, folder, compiled_graph=compiled.graph,
                              reference_path=reference_path)
    return execute_operation(work_root, operation_id, client,
                             target_fingerprint=target_fingerprint, collect=collect,
                             timeout=FORWARD_TIMEOUT)
