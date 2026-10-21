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

from fastapi import APIRouter, HTTPException

from continuable_take import get_take
from continuable_take_api import TakeId
from continuity_pipeline import submit_forward
from continuity_requests import ForwardRequest

FORWARD_PATH = '/{take_id}/forward'


def target_fingerprint(base_url: str, models) -> str:
    """Identity of the machine and weights a graph is allowed to run on."""
    weights = asdict(models) if is_dataclass(models) else dict(models)
    payload = json.dumps({'target': base_url, 'models': weights},
                         sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode()).hexdigest()


def parent_reference(work: str | Path, take_id: str) -> Path:
    """The character reference the parent take was generated with.

    A continuation must reuse the identity the take already carries. Asking the
    operator to upload it again would be both redundant and a chance to drift.
    """
    record = get_take(work, take_id)
    origin = getattr(record, 'origin', None)
    job_id = getattr(origin, 'source_job', None)
    if not job_id:
        raise ValueError('This take has no origin job, so its reference is unknown')
    import core  # local: keeps the module importable without the job store

    job = core.Job.load(job_id)
    if job is None:
        raise ValueError('The take origin job is no longer available')
    references = (job.meta or {}).get('h3_references') or []
    if not references:
        raise ValueError('The take origin job recorded no character reference')
    path = Path(references[0])
    if not path.is_file():
        raise ValueError('The take character reference file is missing')
    return path


def make_forward_runner(*, client_factory, models_factory, fingerprint, work_root):
    """Build the production runner once, so the route stays free of wiring."""
    def run(work, take_id, request):
        reference_path = parent_reference(work, take_id)
        client = client_factory()
        reference = client.assets.from_file(reference_path).as_reference()
        return submit_forward(work, take_id, request, client=client,
                              models=models_factory(), reference=reference,
                              target_fingerprint=fingerprint, work_root=work_root)
    return run


def create_forward_router(get_work_dir, *, runner=None) -> APIRouter:
    router = APIRouter(prefix='/api/continuity/takes', tags=['continuity'])

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

    return router
