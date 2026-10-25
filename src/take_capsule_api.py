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
from model_catalog import validate_bindings
from take_artifacts import anchor_entries, anchor_path


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
    anchors = [
        {key: entry[key] for key in ("segment", "start", "end", "source_frame")}
        | _asset(anchor_path(job, entry["segment"]), "flux_anchor")
        for entry in anchor_entries(job)
    ]
    assets = {"source": source, "references": references, "anchors": anchors,
              "result": _asset(result_path, "edited_video")}
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
        "created": job.created, "engine": job.engine,
        "recipe": copy.deepcopy(job.meta.get("take_recipe")),
        "shot_boundaries": copy.deepcopy(shots), "assets": assets,
        "replay": {
            "available_on_this_machine": replayable, "missing_local_assets": missing,
            "contract": "Replays the recorded recipe with verified local source and reference bytes; pixel-identical output is not guaranteed.",
            "model_weights_hashed": False,
        },
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    manifest["capsule_id"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return manifest


def freeze_take_capsule(job: core.Job, result_path: Path) -> None:
    """Persist the completed take's canonical recipe and input byte fingerprints."""
    job.meta["take_capsule"] = build_take_capsule(job, result_path)


def _frozen_capsule(job: core.Job) -> dict[str, Any] | None:
    capsule = job.meta.get("take_capsule")
    return copy.deepcopy(capsule) if isinstance(capsule, dict) else None


def _replay_options(recipe: dict[str, Any], references: list[dict[str, Any]],
                    shots: list[dict[str, Any]]) -> dict[str, Any]:
    from job_api import _pipeline_options
    paths = [Path(item["image"]) for item in references]
    return _pipeline_options(recipe, paths) | {
        "upscale": recipe["upscale"],
        "shots": [{"start": shot["start"], "end": shot["end"]} for shot in shots],
    }


def _replay_inputs(parent: core.Job):
    capsule = _frozen_capsule(parent)
    recipe = (capsule or {}).get("recipe", parent.meta.get("take_recipe"))
    if not isinstance(recipe, dict) or recipe.get("schema_version") != 1:
        raise HTTPException(409, "This older take has no replayable recipe.")
    try:
        validate_bindings(recipe.get('model_files'))
    except ValueError as exc:
        raise HTTPException(409, "This take has no valid frozen model bindings.") from exc
    source, references = Path(parent.video), parent.meta.get("references", [])
    shots = (capsule or {}).get("shot_boundaries", parent.meta.get("shots", []))
    if not shots:
        raise HTTPException(409, "This take has no recorded shot boundaries and cannot be faithfully replayed.")
    if not source.is_file() or any(not Path(ref["image"]).is_file() for ref in references):
        raise HTTPException(409, "A local source or reference asset is missing; this take cannot be replayed here.")
    if capsule:
        expected = [capsule["assets"]["source"], *capsule["assets"]["references"]]
        actual = [source, *(Path(ref["image"]) for ref in references)]
        if len(expected) != len(actual) or any(item.get("sha256") != _digest_file(path)
                                           for item, path in zip(expected, actual)):
            raise HTTPException(409, "A local source or reference asset changed after this capsule was frozen.")
    # A stored receipt stays readable; a new execution obeys the current budget.
    from source_clip import validate_selection
    try:
        validate_selection({"duration": recipe["frames"] / recipe["fps"]}, label="LTX")
    except (ValueError, KeyError, ZeroDivisionError, TypeError) as exc:
        raise HTTPException(409, "This take exceeds the current 15-second Swap budget or has no valid timing. Select an excerpt for a new take.") from exc
    return recipe, source, references, shots


def _create_child(parent: core.Job, project_id: str | None = None,
                  recipe: dict[str, Any] | None = None) -> core.Job:
    meta = copy.deepcopy(parent.meta)
    if recipe is not None:
        # The frozen capsule, not mutable parent metadata, is replay authority.
        meta['take_recipe'] = copy.deepcopy(recipe)
    meta["parent_job_id"] = parent.id
    if project_id is not None:
        meta["origin_project_id"] = project_id
    prompt = recipe.get('effective_edit_prompt', parent.prompt) if recipe is not None else parent.prompt
    child = core.Job(id=uuid.uuid4().hex, engine=parent.engine, prompt=prompt,
                     video=parent.video, meta=meta)
    child.save()
    return child


class TakeCapsuleAPI:
    def __init__(self, dispatch_job: Callable, readiness_check: Callable, model_readiness_check=None):
        self.dispatch_job = dispatch_job
        self.readiness_check = readiness_check
        self.model_readiness_check = model_readiness_check or (lambda models: readiness_check())

    def get_source(self, job_id: str):
        try:
            source = Path(core.Job.load(job_id).video)
        except KeyError as exc:
            raise HTTPException(404, "Job not found") from exc
        if not source.is_file():
            raise HTTPException(404, "The local source video is unavailable.")
        return FileResponse(source, media_type=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
                            filename=source.name, content_disposition_type="inline")

    def get_anchor(self, job_id: str, segment: int):
        try:
            job = core.Job.load(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Job not found") from exc
        anchor = anchor_path(job, segment)
        if anchor is None:
            raise HTTPException(404, "The recorded FLUX anchor is unavailable.")
        return FileResponse(anchor, media_type=mimetypes.guess_type(anchor.name)[0] or "image/png",
                            filename=f"opengenjutsu-{job_id}-anchor-{segment + 1}{anchor.suffix}",
                            content_disposition_type="inline")

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
        manifest = _frozen_capsule(job) or build_take_capsule(job, result_path)
        if download:
            body = json.dumps(manifest, indent=2, ensure_ascii=False)
            return Response(body, media_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="opengenjutsu-take-{job.id}.json"'})
        return JSONResponse(manifest)

    async def replay_take(self, job_id: str, payload: dict | None = None):
        from project_scope import submission_project
        project_id = submission_project((payload or {}).get("project_id"), core.WORK / "media")
        try:
            parent = core.Job.load(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Job not found") from exc
        if parent.status != "done" or not parent.result:
            raise HTTPException(409, "Only a completed take can be replayed.")
        recipe, source, references, shots = _replay_inputs(parent)
        readiness = self.model_readiness_check(recipe["model_files"])
        if not readiness.get("ready"):
            raise HTTPException(503, detail=" ".join(readiness.get("issues", [])))
        child = _create_child(parent, project_id, recipe)
        self.dispatch_job(child, source, _replay_options(recipe, references, shots))
        return {"job_id": child.id, "project_id": project_id, "parent_job_id": parent.id, "status": "queued",
                "job": {"id": child.id, "status": child.status,
                        "source_url": f"/api/jobs/{child.id}/source", "parent_job_id": parent.id}}


def create_router(dispatch_job: Callable[[core.Job, Path, dict[str, Any]], Any],
                  readiness_check: Callable[[], dict[str, Any]], *, model_readiness_check=None) -> APIRouter:
    api, router = TakeCapsuleAPI(dispatch_job, readiness_check, model_readiness_check), APIRouter()
    router.add_api_route("/api/jobs/{job_id}/source", api.get_source, methods=["GET"])
    router.add_api_route("/api/jobs/{job_id}/anchors/{segment}", api.get_anchor, methods=["GET"])
    router.add_api_route("/api/jobs/{job_id}/capsule", api.get_capsule, methods=["GET"])
    router.add_api_route("/api/jobs/{job_id}/replay", api.replay_take, methods=["POST"], status_code=202)
    return router
