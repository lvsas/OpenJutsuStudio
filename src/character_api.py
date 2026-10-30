"""HTTP boundary for asynchronous FLUX 3 Character jobs."""
import asyncio
import copy
import json
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
import core
from api_schema import _public_project_id
from project_scope import submission_project
from character_capsule import contained, get_capsule, replay_recipe
from character_recipe import ENGINE, make_recipe
from character_library import CharacterLibrary, LibraryError, validate_id


def _load(job_id):
    try:
        validate_id(job_id)
        job = core.Job.load(job_id)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Character job not found") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(409, "Character job record is unavailable") from exc
    if job.engine != ENGINE or job.id != job_id:
        raise HTTPException(404, "Character job not found")
    if not isinstance(job.meta, dict):
        raise HTTPException(409, "Character job record is unavailable")
    return job


def _public(job):
    mode = job.meta.get("character_recipe", {}).get("mode")
    return {"job_id": job.id, "status": job.status, "step": job.step, "progress": job.progress,
            "error": job.error or None,
            "parent_job_id": job.meta.get("parent_job_id"), "engine": ENGINE,
            "face_refine": job.meta.get("character_recipe", {}).get("face_refine") is True,
            "mode": mode if mode in ("portrait", "full_body", "turnaround") else None,
            "project_id": _public_project_id(job)}


class CharacterAPI:
    def __init__(self, get_media_dir, readiness_check, dispatch_job):
        self.get_media_dir, self.readiness_check, self.dispatch_job = get_media_dir, readiness_check, dispatch_job
        self.library = CharacterLibrary(get_media_dir)

    def library_list(self):
        try:
            return {"characters": self.library.list()}
        except LibraryError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    def library_save(self, job_id: str, payload: dict):
        try:
            return self.library.save(job_id, payload)
        except LibraryError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    def library_remove(self, job_id: str):
        try:
            return self.library.remove(job_id)
        except LibraryError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    async def readiness(self):
        return await asyncio.to_thread(self.readiness_check)

    async def create_job(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(422, "Character request must be an object")
        owner = payload.get("project_id")
        origin_project_id = submission_project(owner, self.get_media_dir()) if owner is not None else None
        job_id = uuid.uuid4().hex
        try:
            recipe = make_recipe(job_id=job_id, direction=payload.get("direction", ""),
                                 mode=payload.get("mode", "portrait"), trend_id=payload.get("trend_id", "original"),
                                 selections=payload.get("selections", {}),
                                 sampler_seed=payload.get("sampler_seed", 0),
                                 upsampler_seed=payload.get("upsampler_seed", payload.get("sampler_seed", 0)),
                                 upsampler=payload.get("upsampler", False),
                                 face_refine=payload.get("face_refine", False),
                                 direction_facts=payload.get("direction_facts"),
                                 direction_origin=payload.get("direction_origin", "generated"))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        report = await asyncio.to_thread(self.readiness_check, **(
            {"required_graph": recipe["graph_template"]} if recipe["face_refine"] else {}))
        if not report.get("ready"):
            raise HTTPException(503, " ".join(report.get("issues", [])) or "Character runtime is not ready")
        if origin_project_id is None:
            origin_project_id = submission_project(None, self.get_media_dir())
        job = core.Job(id=job_id, engine=ENGINE, prompt=recipe["resolved_request"],
                       meta={"character_recipe": copy.deepcopy(recipe),
                             "origin_project_id": origin_project_id})
        await asyncio.to_thread(job.save)
        try:
            self.dispatch_job(job, {"recipe": recipe, "media_dir": Path(self.get_media_dir())})
        except Exception as exc:
            job.status, job.step, job.error, job.finished = "error", "character_dispatch", "Character dispatch failed", time.time()
            await asyncio.to_thread(job.save)
            raise HTTPException(503, "Character worker queue is unavailable") from exc
        return _public(job)

    def status(self, job_id):
        return _public(_load(job_id))

    def image(self, job_id):
        job = _load(job_id)
        if job.status != "done" or not job.result:
            raise HTTPException(409, "The Character image is not ready yet")
        try:
            return FileResponse(contained(job.result, self.get_media_dir()), media_type="image/png")
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(409, "The Character image is unavailable") from exc

    def base_image(self, job_id):
        job = _load(job_id)
        if job.status != "done" or job.meta.get("character_recipe", {}).get("face_refine") is not True:
            raise HTTPException(409, "The Character base image is not available")
        try:
            path = contained(job.meta.get("character_base_image", ""), self.get_media_dir())
            if (path.suffix.lower() != ".png" or not job.result
                    or path == contained(job.result, self.get_media_dir())):
                raise ValueError("Base image must be a separate PNG")
            return FileResponse(path, media_type="image/png")
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(409, "The Character base image is unavailable") from exc

    def caption(self, job_id):
        job = _load(job_id)
        if job.status != "done":
            raise HTTPException(409, "The Character caption is not ready yet")
        try:
            path = contained(job.meta.get("character_caption", ""), self.get_media_dir())
            return Response(path.read_text(encoding="utf-8"), media_type="text/plain; charset=utf-8")
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(409, "The Character caption is unavailable") from exc

    def capsule(self, job_id):
        job = _load(job_id)
        try:
            return get_capsule(job)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    async def replay(self, job_id: str, payload: dict | None = None):
        origin_project_id = submission_project((payload or {}).get("project_id"), self.get_media_dir())
        parent = _load(job_id)
        try:
            old = await asyncio.to_thread(replay_recipe, parent, self.get_media_dir())
            child_id = uuid.uuid4().hex
            recipe = make_recipe(job_id=child_id, direction=old["raw_direction"], mode=old["mode"],
                                 trend_id=old["trend_id"], selections=old["selections"],
                                 sampler_seed=old["sampler_seed"], upsampler_seed=old["upsampler_seed"],
                                 upsampler=old["upsampler"], direction_origin=old["direction_origin"],
                                 direction_facts=old["direction_facts"],
                                 face_refine=old["face_refine"])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if recipe["face_refine"]:
            report = await asyncio.to_thread(self.readiness_check, required_graph=recipe["graph_template"])
            if not report.get("ready"):
                raise HTTPException(503, " ".join(report.get("issues", [])) or "Character runtime is not ready")
        child = core.Job(id=child_id, engine=ENGINE, prompt=recipe["resolved_request"],
                         meta={"character_recipe": recipe, "parent_job_id": parent.id,
                               "origin_project_id": origin_project_id})
        await asyncio.to_thread(child.save)
        try:
            self.dispatch_job(child, {"recipe": recipe, "media_dir": Path(self.get_media_dir())})
        except Exception as exc:
            child.status, child.step, child.error, child.finished = "error", "character_dispatch", "Character dispatch failed", time.time()
            await asyncio.to_thread(child.save)
            raise HTTPException(503, "Character worker queue is unavailable") from exc
        return _public(child)


def create_router(get_media_dir, readiness_check, dispatch_job):
    api = CharacterAPI(get_media_dir, readiness_check, dispatch_job)
    router = APIRouter(tags=["Characters"])
    router.add_api_route("/api/characters/readiness", api.readiness, methods=["GET"])
    router.add_api_route("/api/characters/library", api.library_list, methods=["GET"])
    router.add_api_route("/api/characters/library/{job_id}", api.library_save, methods=["POST"])
    router.add_api_route("/api/characters/library/{job_id}", api.library_remove, methods=["DELETE"])
    router.add_api_route("/api/characters/jobs", api.create_job, methods=["POST"], status_code=202)
    router.add_api_route("/api/characters/jobs/{job_id}", api.status, methods=["GET"])
    router.add_api_route("/api/characters/jobs/{job_id}/image", api.image, methods=["GET"])
    router.add_api_route("/api/characters/jobs/{job_id}/base-image", api.base_image, methods=["GET"])
    router.add_api_route("/api/characters/jobs/{job_id}/caption", api.caption, methods=["GET"])
    router.add_api_route("/api/characters/jobs/{job_id}/capsule", api.capsule, methods=["GET"])
    router.add_api_route("/api/characters/jobs/{job_id}/replay", api.replay, methods=["POST"], status_code=202)
    return router
