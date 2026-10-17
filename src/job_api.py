"""Local job-submission API for OpenGenjutsu."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

import config
import core
from api_schema import _public_job, _target_size
from prompt_profiles import get_prompt_profile
from uploads import save_video

ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
ALLOWED_REFERENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _validate_uploads(video: UploadFile, edit_prompt: str, reference_image: UploadFile | None,
                      reference_images: list[UploadFile], reference_targets: list[str]):
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Accepted video formats: MP4, MOV, MKV, WebM")
    if not edit_prompt.strip():
        raise HTTPException(422, "Describe the transformation to apply.")
    references = list(reference_images)
    if reference_image is not None:
        references.insert(0, reference_image)
    if len(references) > 2:
        raise HTTPException(422, "Use at most two character reference images.")
    if len(reference_targets) > len(references):
        raise HTTPException(422, "Each character target needs a reference image.")
    if len(references) == 2 and (len(reference_targets) != 2 or any(not target.strip() for target in reference_targets)):
        raise HTTPException(422, "With two character references, identify both visible people before generating.")
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
    return {
        "flux_unet": config.F_UNET_KLEIN, "flux_clip": config.F_CLIP_KLEIN,
        "flux_vae": config.F_VAE_KLEIN, "ltx_unet": config.F_UNET_LTX,
        "ltx_clip": config.F_CLIP_LTX, "video_vae": config.F_VAE_VID,
        "audio_vae": config.F_VAE_AUD, "ripple_lora": config.F_LORA_RIPPLE,
    }


def _build_recipe(edit_prompt: str, target_description: str, reference_targets: list[str],
                  profile: Any, prompt: str, seed: int, strength: float,
                  info: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    return {
        "schema_version": 1, "edit_brief": edit_prompt.strip(),
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
    return {
        "preserve_audio": recipe["preserve_audio"],
        "reference_image": reference_paths[0] if reference_paths else None,
        "reference_images": reference_paths,
        "edit": {"steps": recipe["edit_steps"], "seed": recipe["edit_seed"],
                 "cfg": recipe["edit_cfg"], "megapixels": recipe["edit_megapixels"]},
        "ripple_prompt": recipe["propagation_prompt"],
        "propagate": {
            "frames": recipe["frames"], "seed": recipe["ripple_seed"],
            "fps": recipe["fps"], "width": recipe["width"], "height": recipe["height"],
            "steps": recipe["ripple_steps"], "strength": recipe["ripple_strength"],
            "cfg": recipe["ripple_cfg"], "guide_strength": recipe["guide_strength"],
        },
    }


def _queue_job(job_id: str, engine: str, video: UploadFile, video_path: Path, edit_prompt: str,
              target_description: str, reference_targets: list[str], seed: int,
              strength: float, info: dict[str, Any], reference_paths: list[Path],
              dispatch_job: Callable) -> core.Job:
    profile = get_prompt_profile(engine)
    prompt = profile.compose_frame_edit(edit_prompt, target_description, reference_targets)
    width, height = _target_size(info["width"], info["height"])
    recipe = _build_recipe(edit_prompt, target_description, reference_targets, profile,
                           prompt, seed, strength, info, width, height)
    job = core.Job(
        id=job_id, engine=engine, prompt=prompt, video=str(video_path),
        meta=_job_meta(video, target_description, reference_targets, reference_paths,
                       info, width, height, strength, recipe),
    )
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
        self, video: UploadFile = File(...),
        edit_prompt: str = Form(..., min_length=3, max_length=2000),
        target_description: str = Form(default="", max_length=500),
        seed: int = Form(default=125348341465200, ge=0),
        ripple_strength: float = Form(default=1.35, ge=0.0, le=2.0),
        reference_image: UploadFile | None = File(default=None),
        reference_images: list[UploadFile] = File(default=[]),
        reference_targets: list[str] = Form(default=[]),
    ) -> dict[str, Any]:
        suffix, references, ref_suffixes = _validate_uploads(
            video, edit_prompt, reference_image, reference_images, reference_targets,
        )
        report = await asyncio.to_thread(self.readiness_check)
        if not report["ready"]:
            raise HTTPException(503, " ".join(report["issues"]))
        media_dir = self.get_media_dir()
        media_dir.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        info, video_path, ref_paths = await _store_uploads(
            media_dir, job_id, video, suffix, references, ref_suffixes, self.max_upload_bytes,
        )
        job = _queue_job(job_id, self.engine, video, video_path, edit_prompt, target_description,
                         reference_targets, seed, ripple_strength, info, ref_paths, self.dispatch_job)
        return {"job_id": job.id, "status": "queued", "job": _public_job(job)}


def create_router(get_media_dir: Callable[[], Path], max_upload_bytes: int,
                  readiness_check: Callable[[], dict[str, Any]], dispatch_job: Callable,
                  engine: str) -> APIRouter:
    router = APIRouter()
    api = JobAPI(get_media_dir, max_upload_bytes, readiness_check, dispatch_job, engine)
    router.add_api_route("/api/jobs", api.create_job, methods=["POST"], status_code=202)
    return router
