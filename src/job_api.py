"""Local job-submission API for OpenGenjutsu."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

import core
from model_catalog import LTX_ROLES, effective_bindings, validate_bindings
from api_schema import _public_job, _target_size
from prompt_profiles import PROMPT_POLICY_VERSION, get_prompt_profile
from project_scope import submission_project
from uploads import save_video
from source_clip import extract_excerpt, probe_source, validate_selection

ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
ALLOWED_REFERENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _validate_uploads(video: UploadFile, edit_prompt: str, reference_image: UploadFile | None,
                      reference_images: list[UploadFile], reference_targets: list[str]):
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Accepted video formats: MP4, MOV, MKV, WebM")
    references = list(reference_images)
    if reference_image is not None:
        references.insert(0, reference_image)
    if not references and not edit_prompt.strip():
        raise HTTPException(422, "Add a character reference or optional edit directions.")
    if len(references) > 2:
        raise HTTPException(422, "Use at most two character reference images.")
    if len(reference_targets) > len(references):
        raise HTTPException(422, "Each character target needs a reference image.")
    suffixes = [Path(item.filename or "").suffix.lower() for item in references]
    if any(suffix not in ALLOWED_REFERENCE_SUFFIXES for suffix in suffixes):
        raise HTTPException(415, "Accepted image formats: PNG, JPG, JPEG, WebP")
    return suffix, references, suffixes


async def _store_uploads(media_dir: Path, job_id: str, video: UploadFile, suffix: str,
                         references: list[UploadFile], reference_suffixes: list[str],
                         max_upload_bytes: int):
    video_path = media_dir / f"{job_id}{suffix}"
    info = await save_video(video, video_path, max_upload_bytes)
    reference_paths = []
    for index, uploaded in enumerate(references):
        path = media_dir / f"{job_id}-reference-{index}{reference_suffixes[index]}"
        content = await uploaded.read()
        if not content:
            video_path.unlink(missing_ok=True)
            raise HTTPException(422, "The reference image is empty.")
        path.write_bytes(content)
        reference_paths.append(path)
    if info["frames"] < 9:
        video_path.unlink(missing_ok=True)
        for path in reference_paths:
            path.unlink(missing_ok=True)
        raise HTTPException(422, "The source video must contain at least 9 frames.")
    return info, video_path, reference_paths


def _model_files() -> dict[str, str]:
    bindings = effective_bindings()
    return {key: bindings[key] for key in LTX_ROLES}


def _build_recipe(edit_prompt: str, target_description: str, reference_targets: list[str],
                  profile: Any, prompt: str, seed: int, strength: float,
                  info: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    return {
        "schema_version": 1, "edit_brief": edit_prompt.strip(),
        "prompt_policy_version": PROMPT_POLICY_VERSION,
        "target_description": target_description.strip(),
        "reference_targets": [target.strip() for target in reference_targets],
        "effective_edit_prompt": prompt, "propagation_prompt": profile.propagation_prompt,
        "edit_seed": seed, "edit_steps": 4, "edit_cfg": 1.0, "edit_megapixels": 1.0,
        "ripple_seed": seed, "ripple_steps": 16, "ripple_strength": strength,
        "ripple_cfg": 1.0, "guide_strength": 1.0,
        "frames": info["frames"], "fps": info["fps"], "width": width, "height": height,
        "preserve_audio": True, "upscale": False, "model_files": _model_files(),
    }


def _job_meta(video: UploadFile, target_description: str, reference_targets: list[str],
              reference_paths: list[Path], info: dict[str, Any], width: int, height: int,
              strength: float, recipe: dict[str, Any]) -> dict[str, Any]:
    frames = info["frames"]
    return {
        "source_filename": Path(video.filename or "video").name,
        "target_description": target_description.strip(),
        "reference_image": str(reference_paths[0]) if reference_paths else None,
        "references": [
            {"target": reference_targets[i].strip() if i < len(reference_targets) else "", "image": str(path)}
            for i, path in enumerate(reference_paths)
        ],
        "source_frames": frames, "processed_frames": frames, "trimmed_tail_frames": 0,
        "fps": info["fps"], "width": width, "height": height,
        "ripple_strength": strength, "take_recipe": recipe,
    }


def _pipeline_options(recipe: dict[str, Any], reference_paths: list[Path]) -> dict[str, Any]:
    # Explicit snapshots never consult today's settings. Older partial snapshots
    # retain their recorded names and use declared defaults for absent roles.
    bindings = effective_bindings(validate_bindings(recipe['model_files']))
    model_files = {key: bindings[key] for key in LTX_ROLES}
    return {
        "preserve_audio": recipe["preserve_audio"],
        "reference_image": reference_paths[0] if reference_paths else None,
        "reference_images": reference_paths,
        "edit": {"steps": recipe["edit_steps"], "seed": recipe["edit_seed"],
                 "cfg": recipe["edit_cfg"], "megapixels": recipe["edit_megapixels"],
                 "model_files": dict(model_files)},
        "ripple_prompt": recipe["propagation_prompt"],
        "propagate": {
            "frames": recipe["frames"], "seed": recipe["ripple_seed"],
            "fps": recipe["fps"], "width": recipe["width"], "height": recipe["height"],
            "steps": recipe["ripple_steps"], "strength": recipe["ripple_strength"],
            "cfg": recipe["ripple_cfg"], "guide_strength": recipe["guide_strength"],
            "model_files": dict(model_files),
        },
    }


def _queue_job(job_id: str, engine: str, video: UploadFile, video_path: Path, edit_prompt: str,
              target_description: str, reference_targets: list[str], seed: int,
              strength: float, info: dict[str, Any], reference_paths: list[Path],
              dispatch_job: Callable, project_id: str, source_selection=None, original_source=None) -> core.Job:
    profile = get_prompt_profile(engine)
    prompt = profile.compose_frame_edit(edit_prompt, target_description, reference_targets,
                                        reference_count=len(reference_paths))
    width, height = _target_size(info["width"], info["height"])
    recipe = _build_recipe(edit_prompt, target_description, reference_targets, profile,
                           prompt, seed, strength, info, width, height)
    job = core.Job(
        id=job_id, engine=engine, prompt=prompt, video=str(video_path),
        meta=_job_meta(video, target_description, reference_targets, reference_paths,
                       info, width, height, strength, recipe),
    )
    if source_selection is not None:
        recipe["source_selection"] = source_selection
        job.meta["original_source"] = str(original_source)
    job.meta["origin_project_id"] = project_id
    job.save()
    dispatch_job(job, video_path, _pipeline_options(recipe, reference_paths))
    return job


class JobAPI:
    def __init__(self, get_media_dir: Callable[[], Path], max_upload_bytes: int,
                 readiness_check: Callable[[], dict[str, Any]], dispatch_job: Callable,
                 engine: str):
        self.get_media_dir = get_media_dir
        self.max_upload_bytes = max_upload_bytes
        self.readiness_check = readiness_check
        self.dispatch_job = dispatch_job
        self.engine = engine

    async def create_job(
        self, request: Request, video: UploadFile = File(...),
        edit_prompt: str = Form(default="", max_length=2000),
        target_description: str = Form(default="", max_length=500),
        seed: int = Form(default=125348341465200, ge=0),
        ripple_strength: float = Form(default=1.35, ge=0.0, le=2.0),
        reference_image: UploadFile | None = File(default=None),
        reference_images: list[UploadFile] = File(default=[]),
        reference_targets: list[str] = Form(default=[]),
        project_id: str | None = Form(default=None),
        clip_start_seconds: float | None = Form(default=None),
        clip_end_seconds: float | None = Form(default=None),
    ) -> dict[str, Any]:
        media_dir = self.get_media_dir()
        origin_project_id = submission_project(project_id, media_dir) if project_id is not None else None
        form = await request.form()
        if ("clip_start_seconds" in form or "clip_end_seconds" in form) and (clip_start_seconds is None or clip_end_seconds is None):
            raise HTTPException(422, "Provide both clip_start_seconds and clip_end_seconds")
        suffix, references, ref_suffixes = _validate_uploads(
            video, edit_prompt, reference_image, reference_images, reference_targets,
        )
        report = await asyncio.to_thread(self.readiness_check)
        if not report["ready"]:
            raise HTTPException(503, " ".join(report["issues"]))
        media_dir.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        info, video_path, ref_paths = await _store_uploads(
            media_dir, job_id, video, suffix, references, ref_suffixes, self.max_upload_bytes,
        )
        original = video_path
        excerpt = media_dir / f"{job_id}-excerpt.mp4"
        selection = None
        try:
            if clip_start_seconds is not None:
                info = await asyncio.to_thread(probe_source, original)
            start, end = validate_selection(info, clip_start_seconds, clip_end_seconds, label="LTX")
            if clip_start_seconds is not None:
                info, selection = await asyncio.to_thread(extract_excerpt, original, excerpt, info, start, end)
                video_path = excerpt
                if info["frames"] < 9:
                    raise ValueError("The selected excerpt must contain at least 9 frames")
        except Exception as exc:
            original.unlink(missing_ok=True)
            for path in ref_paths:
                path.unlink(missing_ok=True)
            if isinstance(exc, ValueError):
                raise HTTPException(422, str(exc)) from exc
            raise HTTPException(422, "The selected excerpt could not be prepared") from exc
        if origin_project_id is None:
            origin_project_id = submission_project(None, media_dir)
        job = _queue_job(job_id, self.engine, video, video_path, edit_prompt, target_description,
                         reference_targets, seed, ripple_strength, info, ref_paths, self.dispatch_job,
                         origin_project_id, selection, original)
        return {"job_id": job.id, "status": "queued", "job": _public_job(job)}


def create_poster_router(resolve_result: Callable, get_store: Callable) -> APIRouter:
    """Wire with the original get_result endpoint, preserving its access checks.

    Registration belongs in the app after get_result is defined. A resolver must
    return the original validated FileResponse, never a client-supplied path.
    """
    from fastapi.responses import FileResponse
    from swap_preview import prepare_poster, PreviewUnavailable
    from timeline_swap_sources import swap_source
    from timeline_store import TimelineError

    router = APIRouter()

    @router.get('/api/jobs/{job_id}/poster')
    def poster(job_id: str):
        result = resolve_result(job_id)  # Preserve the original result access gate.
        try:
            store = get_store()
            source, _ = swap_source(store, job_id)  # Existing done/media-safe validator.
            if source != Path(result.path).absolute():
                raise HTTPException(409, 'The Swap result changed. Try again.')
            path = prepare_poster(store.work, source)
        except TimelineError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        except PreviewUnavailable as exc:
            raise HTTPException(503, str(exc), headers={'Retry-After': '2'}) from exc
        return FileResponse(path, media_type='image/jpeg',
                            headers={'Cache-Control': 'private, no-cache'})

    return router


def create_router(get_media_dir: Callable[[], Path], max_upload_bytes: int,
                  readiness_check: Callable[[], dict[str, Any]], dispatch_job: Callable,
                  engine: str) -> APIRouter:
    router = APIRouter()
    api = JobAPI(get_media_dir, max_upload_bytes, readiness_check, dispatch_job, engine)
    router.add_api_route("/api/jobs", api.create_job, methods=["POST"], status_code=202)
    return router
