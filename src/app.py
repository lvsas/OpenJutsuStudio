#!/usr/bin/env python3
"""Small, local-first web app for OpenGenjutsu's LTX 2.5 + Ripple pipeline."""
from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

import sys
sys.path.insert(0, str(Path(__file__).parent))
import core
from api_schema import _public_job, _target_size
from readiness import check_readiness
from output_media import build_comparison_reel
from job_api import create_router as create_job_router
from take_capsule_api import create_router as create_take_capsule_router
from runtime_inventory import declared_runtime_inventory

DEFAULT_ENGINE = "ltx25-ripple"

app = FastAPI(title="OpenGenjutsu LTX", version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
MAX_UPLOAD_BYTES = int(os.getenv("OPENGENJUTSU_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
MEDIA_DIR = core.WORK / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="opengenjutsu")
PIPELINE_RUNNER = core.run_pipeline


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


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return PAGE


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


def _reveal_path(job_id: str) -> Path:
    return MEDIA_DIR / f"reveal_{job_id}.mp4"


def _completed_job_media(job_id: str) -> tuple[core.Job, Path, Path]:
    try:
        job = core.Job.load(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    if job.status != "done" or not job.result:
        raise HTTPException(status_code=409, detail="The result is not ready yet.")
    source, result = Path(job.video), _result_path(job.result)
    if not source.is_file() or result is None:
        raise HTTPException(status_code=404, detail="The source or result file is not available on this machine.")
    return job, source.resolve(), result


@app.post("/api/jobs/{job_id}/reveal")
def create_reveal(job_id: str) -> dict[str, str]:
    """Create a local 9:16 source/result comparison reel for one completed job."""
    _, source, result = _completed_job_media(job_id)
    output = _reveal_path(job_id)
    try:
        build_comparison_reel(source, result, output)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not build comparison reel: {exc}") from exc
    return {"reveal_url": f"/api/jobs/{job_id}/reveal"}


@app.get("/api/jobs/{job_id}/reveal")
def get_reveal(job_id: str, download: bool = False) -> FileResponse:
    _completed_job_media(job_id)
    path = _reveal_path(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Build the comparison reel first.")
    return FileResponse(path, media_type="video/mp4", filename=f"opengenjutsu-{job_id}-comparison.mp4",
                        content_disposition_type="attachment" if download else "inline")


PAGE = (Path(__file__).parent / "templates" / "index.html").read_text()
