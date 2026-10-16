"""Local Take Capsule API: recipe provenance, hashes, replay, and lineage."""
from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

import core


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset(path: Path | None, role: str) -> dict[str, Any]:
    exists = bool(path and path.is_file())
    return {
        "role": role, "available": exists,
        "sha256": _digest_file(path) if exists and path else None,
        "size_bytes": path.stat().st_size if exists and path else None,
    }


def _resolve_result(result: str) -> Path | None:
    candidate = Path(result)
    options = [candidate] if candidate.is_absolute() else [
        Path.cwd() / candidate, core.WORK / "media" / candidate, core.WORK / candidate,
    ]
    return next((item.resolve() for item in options if item.is_file()), None)


def _capsule_assets(job: core.Job, result_path: Path):
    source = _asset(Path(job.video) if job.video else None, "source_video")
    references = [
        {"target": ref.get("target", ""), **_asset(Path(ref["image"]), f"reference_{i + 1}")}
        for i, ref in enumerate(job.meta.get("references", [])) if ref.get("image")
    ]
    assets = {"source": source, "references": references, "result": _asset(result_path, "edited_video")}
    shots = job.meta.get("shots", [])
    missing = [asset["role"] for asset in [source, *references] if not asset["available"]]
    replayable = bool(job.meta.get("take_recipe") and shots and source["available"]
                      and all(ref["available"] for ref in references))
    return assets, shots, missing, replayable


def build_take_capsule(job: core.Job, result_path: Path) -> dict[str, Any]:
    """Build a path-free manifest; assets stay on this machine."""
    assets, shots, missing, replayable = _capsule_assets(job, result_path)
    manifest: dict[str, Any] = {
        "format": "opengenjutsu-take-capsule", "schema_version": 1,
        "job_id": job.id, "parent_job_id": job.meta.get("parent_job_id"),
        "created": job.created, "engine": job.engine, "recipe": job.meta.get("take_recipe"),
        "shot_boundaries": shots, "assets": assets,
        "replay": {
            "available_on_this_machine": replayable, "missing_local_assets": missing,
            "contract": "Replays the recorded recipe with available local models; pixel-identical output is not guaranteed.",
            "model_weights_hashed": False,
        },
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    manifest["capsule_id"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return manifest


def _replay_options(recipe: dict[str, Any], references: list[dict[str, Any]],
                    shots: list[dict[str, Any]]) -> dict[str, Any]:
    paths = [Path(item["image"]) for item in references]
    return {
        "preserve_audio": recipe["preserve_audio"], "upscale": recipe["upscale"],
        "reference_image": paths[0] if paths else None, "reference_images": paths,
        "edit": {"steps": recipe["edit_steps"], "seed": recipe["edit_seed"],
                 "cfg": recipe["edit_cfg"], "megapixels": recipe["edit_megapixels"]},
        "ripple_prompt": recipe["propagation_prompt"],
        "propagate": {
            "frames": recipe["frames"], "seed": recipe["ripple_seed"],
            "fps": recipe["fps"], "width": recipe["width"], "height": recipe["height"],
            "steps": recipe["ripple_steps"], "strength": recipe["ripple_strength"],
            "cfg": recipe["ripple_cfg"], "guide_strength": recipe["guide_strength"],
        },
        "shots": [{"start": shot["start"], "end": shot["end"]} for shot in shots],
    }


def _replay_inputs(parent: core.Job):
    recipe = parent.meta.get("take_recipe")
    if not isinstance(recipe, dict) or recipe.get("schema_version") != 1:
        raise HTTPException(409, "This older take has no replayable recipe.")
    source, references, shots = Path(parent.video), parent.meta.get("references", []), parent.meta.get("shots", [])
    if not shots:
        raise HTTPException(409, "This take has no recorded shot boundaries and cannot be faithfully replayed.")
    if not source.is_file() or any(not Path(ref["image"]).is_file() for ref in references):
        raise HTTPException(409, "A local source or reference asset is missing; this take cannot be replayed here.")
    return recipe, source, references, shots


def _create_child(parent: core.Job) -> core.Job:
    meta = copy.deepcopy(parent.meta)
    meta["parent_job_id"] = parent.id
    child = core.Job(id=uuid.uuid4().hex, engine=parent.engine, prompt=parent.prompt,
                     video=parent.video, meta=meta)
    child.save()
    return child


class TakeCapsuleAPI:
    def __init__(self, dispatch_job: Callable, readiness_check: Callable):
        self.dispatch_job = dispatch_job
        self.readiness_check = readiness_check

    def get_source(self, job_id: str):
        try:
            source = Path(core.Job.load(job_id).video)
        except KeyError as exc:
            raise HTTPException(404, "Job not found") from exc
        if not source.is_file():
            raise HTTPException(404, "The local source video is unavailable.")
        return FileResponse(source, media_type=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
                            filename=source.name, content_disposition_type="inline")

    def get_capsule(self, job_id: str, download: bool = False):
        try:
            job = core.Job.load(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Job not found") from exc
        if job.status != "done" or not job.result:
            raise HTTPException(409, "The take capsule is available after a completed result.")
        result_path = _resolve_result(job.result)
        if result_path is None:
            raise HTTPException(404, "The local result video is unavailable.")
        manifest = build_take_capsule(job, result_path)
        if download:
            body = json.dumps(manifest, indent=2, ensure_ascii=False)
            return Response(body, media_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="opengenjutsu-take-{job.id}.json"'})
        return JSONResponse(manifest)

    async def replay_take(self, job_id: str):
        try:
            parent = core.Job.load(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Job not found") from exc
        if parent.status != "done" or not parent.result:
            raise HTTPException(409, "Only a completed take can be replayed.")
        recipe, source, references, shots = _replay_inputs(parent)
        readiness = self.readiness_check()
        if not readiness.get("ready"):
            raise HTTPException(503, detail=" ".join(readiness.get("issues", [])))
        child = _create_child(parent)
        self.dispatch_job(child, source, _replay_options(recipe, references, shots))
        return {"job_id": child.id, "parent_job_id": parent.id, "status": "queued",
                "job": {"id": child.id, "status": child.status,
                        "source_url": f"/api/jobs/{child.id}/source", "parent_job_id": parent.id}}


def create_router(dispatch_job: Callable[[core.Job, Path, dict[str, Any]], Any],
                  readiness_check: Callable[[], dict[str, Any]]) -> APIRouter:
    api, router = TakeCapsuleAPI(dispatch_job, readiness_check), APIRouter()
    router.add_api_route("/api/jobs/{job_id}/source", api.get_source, methods=["GET"])
    router.add_api_route("/api/jobs/{job_id}/capsule", api.get_capsule, methods=["GET"])
    router.add_api_route("/api/jobs/{job_id}/replay", api.replay_take, methods=["POST"], status_code=202)
    return router
