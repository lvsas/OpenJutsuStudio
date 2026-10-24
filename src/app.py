#!/usr/bin/env python3
"""Small, local-first web app for OpenGenjutsu's LTX 2.5 + Ripple pipeline."""
from __future__ import annotations

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

import sys
sys.path.insert(0, str(Path(__file__).parent))
import core
from api_schema import _public_job, _target_size
from readiness import check_readiness
from share_reel_api import ReelService, create_router as create_share_reel_router
from job_api import create_router as create_job_router
from take_capsule_api import create_router as create_take_capsule_router
from runtime_inventory import declared_runtime_inventory
from h3_studio_app import register_optional_h3
from comfy_transport import make_client
from config import comfy_base_url
from continuity_forward_api import (create_forward_router, make_forward_runner,
                                    parent_references, refine_prompt, target_fingerprint)
from continuity_attempt_api import create_router as create_attempt_router
from continuity_attempts import Worker
from continuity_pipeline import precheck_request, preflight_continuation, submit_forward
from h3_recipe import H3Models
from h3_continuity_graphs import H3ContinuityModels, Weight


def _continuity_models() -> H3ContinuityModels:
    """The continuity compiler needs Weight objects, not the recipe's filenames."""
    recipe = H3Models()
    # Continuation uses ref2va, the Swap keeps the recipe's fl2va. Measured: with
    # ref2va the motion carries for ~1.2 s past the parent's end; with fl2va the
    # clip cuts three frames in. OPENGENJUTSU_UNET remains as a measurement hook.
    unet = (os.environ.get('OPENGENJUTSU_UNET')
            or 'minimax_h3_ref2va_pruned_int8_convrot.safetensors')
    return H3ContinuityModels(unet=Weight(unet), clip=Weight(recipe.clip),
                              video_vae=Weight(recipe.video_vae),
                              audio_vae=Weight(recipe.audio_vae))
from character_studio_app import register_optional_characters
from timeline_api import create_router as create_timeline_router
from continuable_take_api import create_router as create_continuity_router

DEFAULT_ENGINE = "ltx25-ripple"

app = FastAPI(title="OpenGenjutsu LTX", version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.middleware("http")
async def revalidate_local_assets(request: Request, call_next):
    """Force revalidation of static assets.

    Heuristic freshness otherwise lets a browser keep serving a previous
    stylesheet or script, which silently hides a shipped interface fix.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


MAX_UPLOAD_BYTES = int(os.getenv("OPENGENJUTSU_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
MEDIA_DIR = core.WORK / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="opengenjutsu")
PIPELINE_RUNNER = core.run_pipeline
_REEL_SERVICE = ReelService(lambda: MEDIA_DIR)
app.include_router(create_share_reel_router(_REEL_SERVICE))
app.include_router(create_timeline_router(lambda: core.WORK, lambda: MEDIA_DIR, MAX_UPLOAD_BYTES))
app.include_router(create_continuity_router(lambda: core.WORK))
# A hunt runs on its own single worker: candidates are submitted one at a time,
# and the browser polls a durable record instead of holding a request open.
_HUNT_ROOT = Path(core.WORK) / 'native-attempts'


def _hunt_refine(prompt, take_id, *, mode='forward', second_take_id=None,
                 root_context=None, reference_ids=None, reference_paths=None):
    from continuity_root_pipeline import resolve_root_references, preflight_root
    if mode == 'root':
        paths = resolve_root_references(core.WORK, root_context)
        preflight_root(models=_continuity_models(), direction=prompt,
                       root_context=root_context, raw_frames=277)
    else:
        paths = (tuple(Path(path) for path in reference_paths) if reference_paths is not None else
                 resolve_root_references(core.WORK, {'reference_ids': reference_ids, 'width':32, 'height':32})
                 if reference_ids is not None else parent_references(core.WORK, take_id))
        options = {}
        if mode != 'forward':
            from continuity_composer import operation_options
            ready = operation_options(core.WORK, mode, take_id, second_take_id)
            if not ready['available']:
                raise ValueError(ready['reason'])
            options = {'mode': mode, 'second_take_id': second_take_id,
                       'raw_frames': ready['duration_options'][0]['raw_frames']}
        preflight_continuation(core.WORK, take_id, models=_continuity_models(),
                               direction=prompt, reference_count=len(paths), **options)
    client = make_client()
    references = [client.assets.from_file(path).as_reference() for path in paths]
    return refine_prompt(client, prompt, references)


def _hunt_submit(operation_id, refined, seed, raw_frames, take_id, *, mode='forward',
                 second_take_id=None, root_context=None, reference_ids=None, reference_paths=None):
    from continuity_requests import PreparedH3Request
    import uuid as _uuid
    client = make_client()
    if reference_paths is not None and mode != 'root':
        paths = tuple(Path(path) for path in reference_paths)
    elif mode == 'root' or reference_ids is not None:
        from continuity_root_pipeline import resolve_root_references
        paths = resolve_root_references(core.WORK, root_context if mode == 'root' else
            {'reference_ids': reference_ids, 'width':32, 'height':32})
    else:
        paths = parent_references(core.WORK, take_id)
    references = [client.assets.from_file(path).as_reference() for path in paths]
    request = PreparedH3Request(request_id=_uuid.uuid4().hex, prompt=refined,
                               seed=seed, raw_frames=raw_frames)
    options: dict[str, Any] = dict(client=client, models=_continuity_models(), references=references,
                   target_fingerprint=target_fingerprint(comfy_base_url(), H3Models()),
                   work_root=Path(core.WORK) / 'native-operations', reference_paths=paths,
                   operation_id=operation_id)
    if mode == 'root':
        from continuity_root_pipeline import submit_root
        view = submit_root(core.WORK, request, root_context=root_context, **options)
    elif mode == 'forward':
        view = submit_forward(core.WORK, take_id, request, **options)
    else:
        from continuity_pipeline import submit_continuation
        if not isinstance(take_id,str):
            raise ValueError('An explicit native anchor is required.')
        if mode == 'bridge':
            if not isinstance(second_take_id,str):
                raise ValueError('The second native anchor is required.')
            parents = (take_id, second_take_id)
        else:
            parents = (take_id,)
        view = submit_continuation(core.WORK, parents, request, mode=mode, **options)
    if view['status'] != 'done':
        raise ValueError(view.get('error_detail') or 'The native operation did not complete.')
    return view['take_id']


def _anchored_precheck(take_id, raw, *, mode='forward', second_take_id=None, reference_ids=None):
    from continuity_root_pipeline import resolve_root_references
    paths = (resolve_root_references(core.WORK, {'reference_ids':reference_ids, 'width':32, 'height':32})
             if reference_ids is not None else parent_references(core.WORK, take_id))
    preflight_continuation(core.WORK, take_id, models=_continuity_models(),
                           direction='Read-only dependency check', reference_count=len(paths),
                           raw_frames=raw, mode=mode, second_take_id=second_take_id)


def _root_precheck(context, raw, direction):
    from continuity_root_pipeline import resolve_root_references, preflight_root
    resolve_root_references(core.WORK, context)
    preflight_root(models=_continuity_models(), direction=direction,
                   root_context=context, raw_frames=raw)


def _create_anchored_attempt(root, **intent):
    from continuity_attempts import create_or_get
    from continuity_root_pipeline import resolve_root_references
    ids = intent.get('reference_ids')
    paths = (resolve_root_references(core.WORK, {'reference_ids':ids, 'width':32, 'height':32})
             if ids is not None else parent_references(core.WORK, intent['take_id']))
    # Context files and native Take references are append-only. Freeze their
    # ordered paths in the same atomic attempt, not a mutable pointer to a draft.
    return create_or_get(root, **intent, frozen_reference_paths=[str(p) for p in paths])


_HUNT_WORKER = Worker(_HUNT_ROOT, refine=_hunt_refine, submit=_hunt_submit)
app.include_router(create_attempt_router(
    lambda: _HUNT_ROOT, worker=_HUNT_WORKER, create=_create_anchored_attempt,
    precheck=lambda take_id, raw: precheck_request(core.WORK, take_id, raw),
    anchored_precheck=_anchored_precheck))
from continuity_root_api import create_router as create_root_router
from continuity_composer import create_router as create_composer_router
app.include_router(create_root_router(lambda: core.WORK, lambda: _HUNT_ROOT,
                                     worker=_HUNT_WORKER, precheck=_root_precheck))
app.include_router(create_composer_router(lambda: core.WORK))
app.include_router(create_forward_router(
    lambda: core.WORK,
    runner=make_forward_runner(
        client_factory=make_client, models_factory=_continuity_models,
        fingerprint=target_fingerprint(comfy_base_url(), H3Models()),
        work_root=Path(core.WORK) / 'native-operations')))


def _dispatch_job(job: core.Job, video_path: Path, opts: dict[str, Any]):
    return asyncio.get_running_loop().run_in_executor(
        _EXECUTOR, PIPELINE_RUNNER, job, video_path, opts,
    )


_job_router = create_job_router(
    lambda: MEDIA_DIR, MAX_UPLOAD_BYTES, lambda: check_readiness(),
    _dispatch_job, DEFAULT_ENGINE,
)
app.include_router(_job_router)
create_job = next(route.endpoint for route in _job_router.routes
                  if isinstance(route, APIRoute) and route.path == "/api/jobs")
app.include_router(create_take_capsule_router(_dispatch_job, lambda: check_readiness()))
register_optional_h3(app, _EXECUTOR, lambda: MEDIA_DIR, MAX_UPLOAD_BYTES)
register_optional_characters(app, _EXECUTOR, lambda: MEDIA_DIR)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": DEFAULT_ENGINE}


@app.get("/api/readiness")
def readiness_status():
    report = check_readiness()
    return JSONResponse(report, status_code=200 if report["ready"] else 503)


@app.get("/api/runtime-inventory")
def runtime_inventory() -> dict[str, Any]:
    """Declared local runtime evidence; use readiness for the live machine gate."""
    return declared_runtime_inventory()


TEMPLATES = Path(__file__).parent / "templates"
_PAGE_CACHE: dict[str, tuple[tuple[int, ...], str]] = {}


def _page(name: str) -> str:
    """Read a template, reloading it when it changes on disk.

    The page used to be read once at import, so an edited template silently did not
    appear until the process restarted: a shipped fix could look like a broken change.
    Keyed on the file's modification stamp, so a request stays cheap.
    """
    path = TEMPLATES / name
    # Only these server-owned pages share this fixed fragment. No user path or
    # general-purpose template language is accepted. Track both modification stamps.
    fragment = TEMPLATES / 'export-dialog.html' if name in ('timeline.html', 'assembly.html') else None
    stamp = (path.stat().st_mtime_ns, fragment.stat().st_mtime_ns if fragment else 0)
    cached = _PAGE_CACHE.get(name)
    if cached is None or cached[0] != stamp:
        content = path.read_text()
        if fragment:
            marker = '<!-- shared-export-dialog -->'
            if content.count(marker) != 1:
                raise ValueError('The page must contain exactly one shared export dialog slot')
            content = content.replace(marker, fragment.read_text())
        cached = (stamp, content)
        _PAGE_CACHE[name] = cached
    return cached[1]


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return _page("index.html")


@app.get("/timeline", response_class=HTMLResponse)
def timeline_page() -> str:
    return _page("timeline.html")


@app.get('/assembly', response_class=HTMLResponse)
def assembly_page() -> str:
    return _page('assembly.html')


@app.post("/api/upload-character")
async def upload_character_sheet(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a character sheet image. Returns asset_id for use in job creation."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(415, "Only image uploads are allowed")

    asset_id = uuid.uuid4().hex[:12]
    suffix = Path(file.filename or "ref.png").suffix or ".png"
    dest = MEDIA_DIR / f"char_{asset_id}{suffix}"

    content = await file.read()
    dest.write_bytes(content)

    return {"asset_id": asset_id, "file_path": str(dest), "filename": file.filename}


@app.get("/api/compare")
def compare_frames(job_id: str, segment: int = 0) -> dict[str, Any]:
    """Return source and edited frame paths for side-by-side comparison."""
    try:
        job = core.Job.load(job_id)
    except KeyError:
        raise HTTPException(404, f"Job {job_id} not found")

    # Find source frame for this segment
    source_frame = core.WORK / "media" / f"seg_{segment:03d}_f{job_id}.png"
    if not source_frame.exists():
        # Fallback: look for any segment frame
        candidates = list((core.WORK / "media").glob(f"seg_{segment:03d}_*.png"))
        source_frame = candidates[0] if candidates else None

    # Find edited frame
    edited_frame = None
    if job.result:
        # The result is the final video; edited frame is intermediate
        candidates = list((core.WORK / "media").glob(f"*{job.id}*edited*.png"))
        edited_frame = candidates[0] if candidates else None

    return {
        "job_id": job_id,
        "segment": segment,
        "source_frame": str(source_frame) if source_frame else None,
        "edited_frame": str(edited_frame) if edited_frame else None,
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return [_public_job(j) for j in core.Job.all()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    try:
        return _public_job(core.Job.load(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


def _result_path(result: str) -> Path | None:
    candidate = Path(result)
    options = [candidate] if candidate.is_absolute() else [Path.cwd() / candidate, MEDIA_DIR / candidate]
    options.extend([MEDIA_DIR / Path(result).name, core.WORK / Path(result).name])
    return next((p.resolve() for p in options if p.is_file()), None)


@app.get("/api/jobs/{job_id}/result")
def get_result(job_id: str, download: bool = False) -> FileResponse:
    try:
        job = core.Job.load(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    if job.status != "done" or not job.result:
        raise HTTPException(status_code=409, detail="The result is not ready yet.")
    path = _result_path(job.result)
    if path is None:
        raise HTTPException(status_code=404, detail="The result file is not available on this machine.")
    return FileResponse(path, media_type="video/mp4", filename=f"opengenjutsu-{job_id}.mp4",
                        content_disposition_type="attachment" if download else "inline")


# Templates are read per change rather than once at import: see `_page`.
