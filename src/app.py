#!/usr/bin/env python3
"""Small, local-first web app for OpenGenjutsu's LTX 2.5 + Ripple pipeline."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import sys
sys.path.insert(0, str(Path(__file__).parent))
import core
from api_schema import _public_job, _target_size
from readiness import check_readiness
from prompt_profiles import get_prompt_profile
from uploads import save_video

DEFAULT_ENGINE = "ltx25-ripple"

app = FastAPI(title="OpenGenjutsu LTX", version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
MAX_UPLOAD_BYTES = int(os.getenv("OPENGENJUTSU_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
ALLOWED_REFERENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MEDIA_DIR = core.WORK / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="opengenjutsu")
PIPELINE_RUNNER = core.run_pipeline


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": DEFAULT_ENGINE}


@app.get("/api/readiness")
def readiness_status():
    report = check_readiness()
    return JSONResponse(report, status_code=200 if report["ready"] else 503)


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


def _compose_edit_prompt(edit_prompt: str, target_description: str,
                         reference_targets: list[str] | None = None) -> str:
    """Compatibility wrapper around the default engine's validated profile."""
    return get_prompt_profile(DEFAULT_ENGINE).compose_frame_edit(
        edit_prompt,
        target_description,
        reference_targets,
    )


@app.post("/api/jobs", status_code=202)
async def create_job(
    video: UploadFile = File(...),
    edit_prompt: str = Form(..., min_length=3, max_length=2000),
    target_description: str = Form(default="", max_length=500),
    seed: int = Form(default=125348341465200, ge=0),
    ripple_strength: float = Form(default=1.2, ge=0.0, le=2.0),
    reference_image: UploadFile | None = File(default=None),
    reference_images: list[UploadFile] = File(default=[]),
    reference_targets: list[str] = Form(default=[]),
) -> dict[str, Any]:
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Accepted video formats: MP4, MOV, MKV, WebM")
    if not edit_prompt.strip():
        raise HTTPException(status_code=422, detail="Describe the transformation to apply.")
    uploaded_references = list(reference_images)
    if reference_image is not None:
        uploaded_references.insert(0, reference_image)
    if len(uploaded_references) > 2:
        raise HTTPException(status_code=422, detail="Use at most two character reference images.")
    if len(reference_targets) > len(uploaded_references):
        raise HTTPException(status_code=422, detail="Each character target needs a reference image.")
    reference_suffixes = [Path(item.filename or "").suffix.lower() for item in uploaded_references]
    if any(suffix not in ALLOWED_REFERENCE_SUFFIXES for suffix in reference_suffixes):
        raise HTTPException(status_code=415, detail="Accepted image formats: PNG, JPG, JPEG, WebP")

    report = await asyncio.to_thread(check_readiness)
    if not report["ready"]:
        raise HTTPException(status_code=503, detail=" ".join(report["issues"]))
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    video_path = MEDIA_DIR / f"{job_id}{suffix}"
    info = await save_video(video, video_path, MAX_UPLOAD_BYTES)
    reference_paths: list[Path] = []
    for index, uploaded_reference in enumerate(uploaded_references):
        reference_path = MEDIA_DIR / f"{job_id}-reference-{index}{reference_suffixes[index]}"
        reference_bytes = await uploaded_reference.read()
        if not reference_bytes:
            video_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="The reference image is empty.")
        reference_path.write_bytes(reference_bytes)
        reference_paths.append(reference_path)

    if info["frames"] < 9:
        video_path.unlink(missing_ok=True)
        for reference_path in reference_paths:
            reference_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="The source video must contain at least 9 frames.")

    # Each shot is padded for LTX and trimmed back; source frames are retained.
    source_frames = info["frames"]
    frames = source_frames
    prompt = _compose_edit_prompt(edit_prompt, target_description, reference_targets)
    width, height = _target_size(info["width"], info["height"])
    job = core.Job(
        id=job_id,
        engine=DEFAULT_ENGINE,
        prompt=prompt,
        video=str(video_path),
        meta={
            "source_filename": Path(video.filename or "video").name,
            "target_description": target_description.strip(),
            "reference_image": str(reference_paths[0]) if reference_paths else None,
            "references": [
                {"target": reference_targets[index].strip() if index < len(reference_targets) else "",
                 "image": str(path)}
                for index, path in enumerate(reference_paths)
            ],
            "source_frames": source_frames,
            "processed_frames": frames,
            "trimmed_tail_frames": source_frames - frames,
            "fps": info["fps"],
            "width": width,
            "height": height,
            "ripple_strength": ripple_strength,
        },
    )
    job.save()
    opts = {
        "preserve_audio": True,
        "reference_image": reference_paths[0] if reference_paths else None,
        "reference_images": reference_paths,
        "edit": {"steps": 4, "seed": seed},
        "ripple_prompt": get_prompt_profile(DEFAULT_ENGINE).propagation_prompt,
        "propagate": {
            "frames": frames,
            "seed": seed,
            "fps": round(info["fps"]),
            "width": width,
            "height": height,
            "steps": 16,
            "strength": ripple_strength,
        },
    }
    loop = asyncio.get_running_loop()
    loop.run_in_executor(_EXECUTOR, PIPELINE_RUNNER, job, video_path, opts)
    return {"job_id": job.id, "status": "queued", "job": _public_job(job)}


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


PAGE = (Path(__file__).parent / "templates" / "index.html").read_text()
