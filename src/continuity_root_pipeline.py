"""Parentless roots on the existing native operation/collector lifecycle.

No queue, restage, Swap, or rendering claim lives here. A root has no pins: the
native producer allocates round(frames / 24 * 40) audio ticks, its saver records
zero phase and delivers all raw frames. Require that predicted state to carry a
future tail, then require the downloaded mctx to match it before publication.
"""
from __future__ import annotations

from fractions import Fraction
from io import BytesIO
from pathlib import Path
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from continuable_take import _directory, _open_file
from continuity_attempts import validate_root_context
from continuity_jobs import create_operation, execute_operation
from continuity_pipeline import collect_forward, TargetMissingDependencies, FORWARD_TIMEOUT
from h3_av_state import AVState, audio_ticks, tail_fits
from h3_prompt_generator import build_prompt_graph
from h3_root_graphs import build_h3_root
from readiness import missing_dependencies

MAX_REFERENCE_BYTES = 10 * 1024 * 1024
MAX_REFERENCE_PIXELS = 20_000_000
_IMAGE_MIMES = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}


def validate_image(payload, content_type, *, stored=False):
    """Sniff/decode bounded still images; strip metadata into a validated PNG."""
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_REFERENCE_BYTES:
        raise ValueError('An image must contain at most 10 MiB.')
    if content_type not in _IMAGE_MIMES.values():
        raise ValueError('Use a PNG, JPEG or WebP image with its image MIME type.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as image:
                if _IMAGE_MIMES.get(image.format or '') != content_type:
                    raise ValueError('The image content does not match its MIME type.')
                if (getattr(image, 'n_frames', 1) != 1
                        or image.width * image.height > MAX_REFERENCE_PIXELS):
                    raise ValueError('Use a bounded, non-animated reference image.')
                image.verify()
            with Image.open(BytesIO(payload)) as image:
                image.load()
                if stored:
                    return payload
                pixels = ImageOps.exif_transpose(image).convert('RGBA' if 'A' in image.getbands() else 'RGB')
                # A fresh image cannot carry EXIF, prompt, ICC or ancillary data.
                clean = Image.new(pixels.mode, pixels.size)
                clean.paste(pixels)
                output = BytesIO()
                clean.save(output, format='PNG')
                result = output.getvalue()
                if len(result) > MAX_REFERENCE_BYTES:
                    raise ValueError('The normalized reference exceeds 10 MiB.')
                return result
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise ValueError('The image could not be safely decoded.') from error


def root_state(raw_frames) -> AVState:
    """Pinned native root policy, not a projection borrowed from Forward.

    MiniMax H3 temporal_shape allocates rounded audio ticks; H3ApplyPins with
    no pin_specs leaves the latent intact; H3SaveVideoWithMCtx computes
    pins_audio_phase([], raw_frames) == 0 and head == tail == 0. The collector
    compares actual saved timing with this expectation, failing closed on drift.
    """
    if (type(raw_frames) is not int or not 5 <= raw_frames <= 3600
            or (raw_frames - 5) % 17):
        raise ValueError('H3 frames must follow the native 17k+5 grid.')
    state = AVState(raw_frames, 0, raw_frames, audio_ticks(raw_frames), Fraction(0))
    if not tail_fits(state):
        raise ValueError('This root would be too short for a future continuation. Nothing was submitted.')
    return state


def resolve_root_references(work, root_context) -> tuple[Path, ...]:
    """Resolve only immutable root image IDs, in order, with no symlink hops.

    The existing artifact NOFOLLOW walkers protect ancestors and regular files.
    This read-only function never creates missing media folders or references.
    """
    context = validate_root_context(root_context)
    try:
        media = _directory(Path(work) / 'media')
        paths = []
        for identifier in context['reference_ids']:
            path = media / f'root-reference-{identifier}.png'
            with _open_file(path) as stream:
                data = stream.read(MAX_REFERENCE_BYTES + 1)
            if not data or len(data) > MAX_REFERENCE_BYTES:
                raise ValueError('A root reference is empty or too large.')
            # Only normalized, validated PNGs may be used, even if a local file
            # was substituted outside the browser's append-only upload surface.
            validate_image(data, 'image/png', stored=True)
            paths.append(path)
        return tuple(paths)
    except (OSError, ValueError) as error:
        raise ValueError('A root reference is missing or unsafe. Upload it again.') from error


def preflight_root(*, models, direction, root_context, raw_frames,
                   inventory=missing_dependencies):
    """Compile both authored graphs with N sentinel refs before any paid work.

    Inventory runs on the FINAL expanded root, never a contracted one. The
    default missing_dependencies checks classes/weights without calling the
    pinned single-reference validate_graph_contracts, whose topology guard must
    not be weakened to admit arbitrary root additions. This is dependency
    inventory, not installed autogrow-capacity, filesystem or render evidence.
    """
    context = validate_root_context(root_context)
    root_state(raw_frames)
    refs = [{'__type': 'core/ASSET', 'info': {'id': f'preflight-root-{index}'}}
            for index in range(len(context['reference_ids']))]
    graph = build_h3_root(references=refs, prompt=direction, operation_id='f' * 32,
                          seed=0, width=context['width'], height=context['height'],
                          raw_frames=raw_frames, models=models, publish_family=True).graph
    nodes, weights = set(), set()
    for candidate in (graph, build_prompt_graph(direction, refs)):
        absent_nodes, absent_weights = inventory(candidate)
        nodes.update(absent_nodes)
        weights.update(absent_weights)
    if nodes or weights:
        raise TargetMissingDependencies(sorted(nodes), sorted(weights))


def submit_root(work, request, *, client, models, references, reference_paths,
                root_context, target_fingerprint, work_root, operation_id):
    """Freeze and execute one parentless candidate through the existing SDK.

    Reference uploads/refinement belong to the SAME attempts Worker's callbacks.
    This service accepts already committed SDK refs and verifies their ordered
    local copies against the frozen context before it writes an operation.
    """
    context = validate_root_context(root_context)
    state = root_state(request.raw_frames)
    paths = resolve_root_references(work, context)
    if (not isinstance(reference_paths, (tuple, list))
            or tuple(Path(p).absolute() for p in reference_paths) != paths):
        raise ValueError('Root reference paths differ from the frozen ordered references.')
    if not isinstance(references, (list, tuple)) or len(references) != len(paths):
        raise ValueError('Each root reference needs its ordered committed SDK asset.')
    graph = build_h3_root(references=references, prompt=request.prompt,
                          operation_id=operation_id, seed=request.seed,
                          width=context['width'], height=context['height'],
                          raw_frames=request.raw_frames, models=models, publish_family=True).graph
    create_operation(work_root, operation_id, mode='root', graph=graph,
                     seed=request.seed, parents=(), target_fingerprint=target_fingerprint)
    collect = collect_forward(work, Path(work) / 'media' / f'root-{operation_id}',
                              compiled_graph=graph, reference_paths=paths,
                              operator_label='native-root', expected_state=state)
    return execute_operation(work_root, operation_id, client,
                             target_fingerprint=target_fingerprint, collect=collect,
                             timeout=FORWARD_TIMEOUT)
