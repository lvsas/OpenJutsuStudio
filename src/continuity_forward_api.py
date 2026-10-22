"""HTTP surface for one Forward, wired to the proven runtime chain.

The route stays thin: it validates the request, refuses what costs nothing to
refuse, and delegates. Every dependency is injected so a test can prove the
refusals without a GPU or a network.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

import continuity_context
from continuable_take import get_take
from continuable_take_api import TakeId
from continuity_pipeline import submit_forward
from continuity_requests import ForwardRequest
from h3_prompt_generator import build_prompt_graph, read_prompt_text
from continuity_context import MAX_BYTES, context_references

FORWARD_PATH = '/{take_id}/forward'


def target_fingerprint(base_url: str, models) -> str:
    """Identity of the machine and weights a graph is allowed to run on."""
    weights = asdict(models) if is_dataclass(models) else dict(models)
    payload = json.dumps({'target': base_url, 'models': weights},
                         sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode()).hexdigest()


class MissingHistoricalReferences(ValueError):
    """Legacy take has no usable history; an explicit new context may start empty."""


def parent_references(work: str | Path, take_id: str) -> list[Path]:
    """Prepared references override inheritance, including an explicit empty set."""
    if continuity_context.has_context(work, take_id):
        return context_references(work, take_id)
    return inherited_references(work, take_id)


def inherited_references(work: str | Path, take_id: str) -> list[Path]:
    """Original ordered identity, hash-verified; legacy origin is a fallback only."""
    record = get_take(work, take_id)
    capsule = record.to_manifest()
    folder = Path(work) / 'timeline' / 'continuable-takes' / take_id
    if 'identity' in capsule:
        resolved = []
        for item in capsule['identity']['references']:
            path = folder / item['filename']
            if (path.is_symlink() or not path.is_file()
                    or not 0 < path.stat().st_size <= MAX_BYTES
                    or _sha256(path) != item['sha256']):
                raise ValueError('This take reference no longer matches what it was generated with.')
            resolved.append(path)
        return resolved
    origin = capsule.get('origin') or {}
    job_id = origin.get('source_job')
    if not job_id:
        raise MissingHistoricalReferences('This take has no origin job, so its reference is unknown')
    import core  # local: keeps the module importable without the job store

    try:
        job = core.Job.load(job_id)
    except KeyError:
        raise MissingHistoricalReferences(
            'This take does not record its character reference. Add one below to '
            'continue it.') from None
    references = (job.meta or {}).get('h3_references') or []
    if not references:
        raise MissingHistoricalReferences('The take origin job recorded no character reference')
    paths = [Path(reference) for reference in references]
    for path in paths:
        if not path.is_file():
            raise MissingHistoricalReferences('The take character reference file is missing')
        if path.is_symlink() or not 0 < path.stat().st_size <= MAX_BYTES:
            raise ValueError('The historical reference is unsafe or exceeds the accepted limit')
    return paths


def _seed_context(work, take_id):
    def inherited():
        try:
            return inherited_references(work, take_id)
        except MissingHistoricalReferences:
            return []
    return continuity_context.seed_context(work, take_id, inherited)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def make_forward_runner(*, client_factory, models_factory, fingerprint, work_root):
    """Build the production runner once, so the route stays free of wiring."""
    def run(work, take_id, request):
        paths = parent_references(work, take_id)
        client = client_factory()
        references = [client.assets.from_file(path).as_reference() for path in paths]
        # The operator writes natural language; the refiner turns it into the
        # six-section H3 prompt, reading the references it is handed.
        refined = refine_prompt(client, request.prompt, references)
        request = request.model_copy(update={'prompt': refined})
        return submit_forward(work, take_id, request, client=client,
                              models=models_factory(), references=references,
                              target_fingerprint=fingerprint, work_root=work_root,
                              reference_paths=paths)
    return run


PROMPT_TIMEOUT = 900

def refine_prompt(client, direction: str, references) -> str:
    """Run the R2VA generator on the vision 4B and return its text.

    The 2B was measured on the same guide, picture and direction: it sees the
    image but invents subjects and never reaches all six sections, so one refiner
    stays, and it is the vision 4B.
    """
    graph = build_prompt_graph(direction, references)
    job = client.run(client.workflows.from_json(graph), timeout=PROMPT_TIMEOUT)
    if getattr(job, 'status', None) != 'succeeded':
        raise ValueError('The prompt could not be prepared. Your take is unchanged.')
    return read_prompt_text(job)


def create_forward_router(get_work_dir, *, runner=None) -> APIRouter:
    router = APIRouter(prefix='/api/continuity/takes', tags=['continuity'])

    @router.get('/{take_id}/references')
    def references(take_id: TakeId):
        """Effective next-generation references, in <Picture N> order."""
        try:
            paths = parent_references(str(get_work_dir()), take_id)
        except FileNotFoundError:
            raise HTTPException(404, 'Unknown take') from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return {'references': [
            {'index': position, 'sha256': _sha256(path),
             'url': f'/api/continuity/takes/{take_id}/references/{position}'}
            for position, path in enumerate(paths, start=1)]}

    @router.get('/{take_id}/references/{index}')
    def reference_image(take_id: TakeId, index: int):
        if index < 1:
            raise HTTPException(404, 'Unknown reference')
        try:
            paths = parent_references(str(get_work_dir()), take_id)
        except FileNotFoundError:
            raise HTTPException(404, 'Unknown take') from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        if index > len(paths):
            raise HTTPException(404, 'Unknown reference')
        path = paths[index - 1]
        return FileResponse(path, media_type=_image_type(path),
                            headers={'Cache-Control': 'private, max-age=60'})

    @router.post(FORWARD_PATH, status_code=202)
    def forward(take_id: TakeId, request: ForwardRequest):
        if runner is None:
            raise HTTPException(503, 'Forward is not configured on this instance')
        try:
            view = runner(str(get_work_dir()), take_id, request)
        except FileNotFoundError:
            raise HTTPException(404, 'Unknown take') from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return view

    async def edit_reference(take_id, image, position=None):
        payload = await image.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise HTTPException(413, 'That image is too large')
        suffix = Path(image.filename or '').suffix
        try:
            work = str(get_work_dir())
            _seed_context(work, take_id)
            if position is None:
                manifest = continuity_context.add_reference(work, take_id, payload, suffix)
            else:
                manifest = continuity_context.replace_reference(work, take_id, position, payload, suffix)
        except FileNotFoundError:
            raise HTTPException(404, 'Unknown take') from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {'references': _reference_view(take_id, manifest)}

    @router.post('/{take_id}/references', status_code=201)
    async def add_reference(take_id: TakeId, image: UploadFile = File(...)):
        return await edit_reference(take_id, image)

    @router.put('/{take_id}/references/{position}', status_code=200)
    async def replace_reference(take_id: TakeId, position: int, image: UploadFile = File(...)):
        return await edit_reference(take_id, image, position)

    @router.delete('/{take_id}/references/{position}', status_code=200)
    def remove_reference(take_id: TakeId, position: int):
        try:
            _seed_context(str(get_work_dir()), take_id)
            manifest = continuity_context.remove_reference(
                str(get_work_dir()), take_id, position)
        except FileNotFoundError:
            raise HTTPException(404, 'Unknown take') from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {'references': _reference_view(take_id, manifest)}

    return router


def _reference_view(take_id: str, manifest: dict) -> list[dict]:
    return [{'index': position, 'sha256': item['sha256'],
             'url': f'/api/continuity/takes/{take_id}/references/{position}'}
            for position, item in enumerate(manifest['references'], start=1)]


def _image_type(path: Path) -> str:
    return {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.webp': 'image/webp'}.get(path.suffix.lower(), 'application/octet-stream')
