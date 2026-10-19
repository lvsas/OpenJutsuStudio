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
from character_capsule import contained, get_capsule, replay_recipe
from character_recipe import ENGINE, make_recipe


def _load(job_id):
    try:
        job = core.Job.load(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Character job not found") from exc
    if job.engine != ENGINE:
        raise HTTPException(404, "Character job not found")
    return job


def _public(job):
    return {"job_id": job.id, "status": job.status, "step": job.step, "progress": job.progress,
            "error": job.error, "parent_job_id": job.meta.get("parent_job_id"), "engine": ENGINE}


class CharacterAPI:
    def __init__(self, get_media_dir, readiness_check, dispatch_job):
        self.get_media_dir, self.readiness_check, self.dispatch_job = get_media_dir, readiness_check, dispatch_job

    async def readiness(self):
        return await asyncio.to_thread(self.readiness_check)

    async def create_job(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(422, "Character request must be an object")
        job_id = uuid.uuid4().hex
        try:
            recipe = make_recipe(job_id=job_id, direction=payload.get("direction", ""),
                                 mode=payload.get("mode", "portrait"), trend_id=payload.get("trend_id", "original"),
                                 selections=payload.get("selections", {}),
                                 sampler_seed=payload.get("sampler_seed", 0),
                                 upsampler_seed=payload.get("upsampler_seed", payload.get("sampler_seed", 0)),
                                 upsampler=payload.get("upsampler", True),
                                 direction_origin=payload.get("direction_origin", "generated"))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        report = await asyncio.to_thread(self.readiness_check)
        if not report.get("ready"):
            raise HTTPException(503, " ".join(report.get("issues", [])) or "Character runtime is not ready")
        job = core.Job(id=job_id, engine=ENGINE, prompt=recipe["resolved_request"],
                       meta={"character_recipe": copy.deepcopy(recipe)})
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
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    def caption(self, job_id):
        job = _load(job_id)
        if job.status != "done":
            raise HTTPException(409, "The Character caption is not ready yet")
        try:
            path = contained(job.meta.get("character_caption", ""), self.get_media_dir())
            return Response(path.read_text(encoding="utf-8"), media_type="text/plain; charset=utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(409, "The Character caption is unavailable") from exc

    def capsule(self, job_id):
        job = _load(job_id)
        try:
            return get_capsule(job)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    async def replay(self, job_id):
        parent = _load(job_id)
        try:
            old = await asyncio.to_thread(replay_recipe, parent, self.get_media_dir())
            child_id = uuid.uuid4().hex
            recipe = make_recipe(job_id=child_id, direction=old["raw_direction"], mode=old["mode"],
                                 trend_id=old["trend_id"], selections=old["selections"],
                                 sampler_seed=old["sampler_seed"], upsampler_seed=old["upsampler_seed"],
                                 upsampler=old["upsampler"], direction_origin=old["direction_origin"])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        child = core.Job(id=child_id, engine=ENGINE, prompt=recipe["resolved_request"],
                         meta={"character_recipe": recipe, "parent_job_id": parent.id})
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
    router.add_api_route("/api/characters/jobs", api.create_job, methods=["POST"], status_code=202)
    router.add_api_route("/api/characters/jobs/{job_id}", api.status, methods=["GET"])
    router.add_api_route("/api/characters/jobs/{job_id}/image", api.image, methods=["GET"])
    router.add_api_route("/api/characters/jobs/{job_id}/caption", api.caption, methods=["GET"])
    router.add_api_route("/api/characters/jobs/{job_id}/capsule", api.capsule, methods=["GET"])
    router.add_api_route("/api/characters/jobs/{job_id}/replay", api.replay, methods=["POST"], status_code=202)
    return router
