"""Bounded local reel artifacts for a single Uvicorn process.

One independent encoder, at most four outstanding artifacts (running + queued).
State and ready media survive restart; orphaned pending states become retryable errors.
This is deliberately not a distributed queue: multiple Uvicorn workers are unsupported.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import threading
import uuid
from typing import Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

import core
from media import ffprobe
from output_media import build_comparison_reel, build_social_reel, validate_reel_media

LOG = logging.getLogger(__name__)
# A renderer version is part of an artifact's identity but the design tokens are not in the digest,
# so any visual change to a layout must bump its version. Otherwise a reel already marked ready
# keeps being served with the previous design. social-v4 / wipe-v3: slower shared reveal timing.
RENDERER_VERSIONS = {"social": "social-v4", "wipe": "wipe-v3", "stacked": "stacked-v2"}
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")
ARTIFACT = re.compile(r"[0-9a-f]{64}")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _contained(path: str | Path, work: Path, media: Path) -> Path:
    """Resolve the recorded path only; never guess a same-named fallback file."""
    candidate = Path(path)
    candidates = [candidate] if candidate.is_absolute() else [Path.cwd() / candidate, work / candidate, media / candidate]
    for item in candidates:
        resolved = item.resolve()
        if (resolved.is_relative_to(work) or resolved.is_relative_to(media)) and resolved.is_file():
            return resolved
    raise HTTPException(404, "The local source or result is missing or outside the workspace.")


@dataclass(frozen=True)
class Inputs:
    job: core.Job
    source: Path
    original: Path
    result: Path
    work: Path
    media: Path
    identity: dict


class ReelService:
    def __init__(self, media_dir: Callable[[], Path], *, capacity: int = 4):
        self.media_dir = media_dir
        self.capacity = capacity
        self._lock = threading.RLock()
        self._active: set[tuple[str, str, str]] = set()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="share-reel")

    def close(self):
        """Drain accepted work (also used by isolated tests)."""
        self._executor.shutdown(wait=True)

    def inputs(self, job_id: str, layout: str) -> Inputs:
        if layout not in RENDERER_VERSIONS:
            raise HTTPException(400, "Unknown reel layout.")
        try:
            job = core.Job.load(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Job not found.") from exc
        if job.id != job_id:
            raise HTTPException(404, "Job not found.")
        if job.status != "done" or not job.result:
            raise HTTPException(409, "The result is not ready yet.")
        work, media = core.WORK.resolve(), Path(self.media_dir()).resolve()
        if not job.video:
            raise HTTPException(404, "The source file is not available.")
        original = _contained(job.video, work, media)
        result = _contained(job.result, work, media)
        source = original
        if job.engine == "minimax-h3":
            # h3_pipeline.run_h3_pipeline -> h3_media.prepare_source. Never use padded.mp4.
            normalized = media / f"h3-{job.id}" / "normalized.mp4"
            if normalized.exists():
                source = _contained(normalized, work, media)
                if source != normalized.absolute():
                    raise HTTPException(404, "The normalized source is outside this take's workspace.")
        try:
            hashes = {path: _digest(path) for path in {source, result, original}}
        except OSError as exc:
            raise HTTPException(404, "A local reel input became unavailable.") from exc
        identity = {"job_id": job.id, "layout": layout, "engine": job.engine,
                    "renderer_version": RENDERER_VERSIONS[layout],
                    "source_sha256": hashes[source], "result_sha256": hashes[result],
                    "original_sha256": hashes[original],
                    "source_kind": "normalized" if source != original else "original"}
        return Inputs(job, source, original, result, work, media, identity)

    @staticmethod
    def _directory(media: Path, job_id: str, artifact_id: str) -> Path:
        if not IDENTIFIER.fullmatch(job_id) or not ARTIFACT.fullmatch(artifact_id):
            raise HTTPException(404, "Reel not found.")
        root = media.resolve()
        directory = root / "reels" / job_id / artifact_id
        # Resolve every component, including a pre-existing artifact-directory symlink.
        if directory.resolve() != directory:
            raise HTTPException(404, "Reel not found.")
        return directory

    @staticmethod
    def _write(directory: Path, state: dict):
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f".{uuid.uuid4().hex}.part.json"
        try:
            temporary.write_text(json.dumps(state, sort_keys=True))
            os.replace(temporary, directory / "state.json")
        finally:
            temporary.unlink(missing_ok=True)

    def _read(self, media: Path, job_id: str, artifact_id: str) -> dict:
        directory = self._directory(media, job_id, artifact_id)
        path = directory / "state.json"
        if path.is_symlink():
            raise HTTPException(404, "Reel not found.")
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise HTTPException(404, "Reel not found.") from exc
        if not isinstance(state, dict) or not isinstance(state.get("identity"), dict):
            raise HTTPException(404, "Reel not found.")
        identity = state["identity"]
        if (identity.get("job_id") != job_id or _json_digest(identity) != artifact_id
                or identity.get("layout") not in RENDERER_VERSIONS
                or state.get("status") not in {"queued", "running", "ready", "error"}):
            raise HTTPException(404, "Reel not found.")
        key = (str(media), job_id, artifact_id)
        if state["status"] in {"queued", "running"} and key not in self._active:
            state.update(status="error", error="Reel creation was interrupted. Retry to build it again.")
            self._remove_parts(directory)
            self._write(directory, state)
        output = directory / "reel.mp4"
        if state["status"] == "ready" and (output.is_symlink() or not output.is_file() or output.stat().st_size == 0):
            state.update(status="error", error="The ready reel is no longer available. Retry to build it again.")
            self._write(directory, state)
        return state

    @staticmethod
    def _public(state: dict) -> dict:
        identity = state["identity"]
        artifact_id = _json_digest(identity)
        job_id, layout = identity["job_id"], identity["layout"]
        status_url = f"/api/jobs/{job_id}/reels/{artifact_id}"
        ready = state["status"] == "ready"
        result = {"artifact_id": artifact_id, "job_id": job_id, "layout": layout,
                  "renderer_version": identity["renderer_version"], "status": state["status"],
                  "status_url": status_url,
                  "preview_url": status_url + "/media" if ready else None,
                  "download_url": status_url + "/media?download=true" if ready else None,
                  "filename": f"opengenjutsu-{job_id}-{layout}-{artifact_id[:12]}.mp4"}
        if state["status"] == "error":
            result["error"] = state.get("error", "Could not create reel. Retry to build it again.")
        return result

    def request(self, job_id: str, layout: str, retry: bool = False) -> dict:
        inputs = self.inputs(job_id, layout)
        artifact_id = _json_digest(inputs.identity)
        directory = self._directory(inputs.media, job_id, artifact_id)
        key = (str(inputs.media), job_id, artifact_id)
        with self._lock:
            try:
                previous = self._read(inputs.media, job_id, artifact_id)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                previous = None
            if previous and (previous["status"] != "error" or not retry):
                return self._public(previous)
            if len(self._active) >= self.capacity:
                raise HTTPException(429, "The reel queue is full. Try again shortly.", headers={"Retry-After": "2"})
            state = {"identity": inputs.identity, "status": "queued"}
            self._write(directory, state)
            self._active.add(key)
            try:
                self._executor.submit(self._render, inputs, directory, key, state)
            except Exception:
                self._active.discard(key)
                state.update(status="error", error="The reel worker is unavailable. Retry to build it again.")
                self._write(directory, state)
                raise HTTPException(503, "The reel worker is unavailable.") from None
            return self._public(state)

    def status(self, job_id: str, artifact_id: str) -> dict:
        with self._lock:
            return self._public(self._read(Path(self.media_dir()).resolve(), job_id, artifact_id))

    @staticmethod
    def _remove_parts(directory: Path):
        for path in directory.glob(".*.part*"):
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)

    @staticmethod
    def _verify_inputs(inputs: Inputs):
        verified = {}
        for path, role in ((inputs.source, "source"), (inputs.result, "result"), (inputs.original, "original")):
            if path not in verified:
                if _contained(path, inputs.work, inputs.media) != path:
                    raise ValueError("A reel input moved")
                verified[path] = _digest(path)
            if verified[path] != inputs.identity[f"{role}_sha256"]:
                raise ValueError("A reel input changed")

    @staticmethod
    def _validate_h3(inputs: Inputs, source_info: dict, result_info: dict):
        if inputs.job.engine != "minimax-h3":
            return
        from h3_capsule import get_capsule
        capsule = get_capsule(inputs.job)
        for role, path in (("source", inputs.original), ("result", inputs.result)):
            asset = capsule["assets"][role]
            digest = inputs.identity["original_sha256" if role == "source" else "result_sha256"]
            if asset["sha256"] != digest or asset["size_bytes"] != path.stat().st_size:
                raise ValueError("The H3 take no longer matches its provenance")
        count = capsule["recipe"]["source_frames_24fps"]
        original_info = ffprobe(inputs.original)
        if (abs(source_info["fps"] - 24) > 0.001 or source_info["frames"] != count
                or result_info["frames"] != count
                or abs(original_info["duration"] - count / 24) > max(1 / original_info["fps"], 1 / 24) + 0.001):
            raise ValueError("The H3 comparison does not match its unpadded source timeline")

    def _render(self, inputs: Inputs, directory: Path, key: tuple, state: dict):
        # Keep .mp4 as the final suffix so ffmpeg can infer the container.
        partial = directory / f".{uuid.uuid4().hex}.part.mp4"
        output = directory / "reel.mp4"
        published = False
        try:
            with self._lock:
                state = {**state, "status": "running"}
                self._write(directory, state)
            self._verify_inputs(inputs)
            source_info, result_info = validate_reel_media(inputs.source, inputs.result)
            self._validate_h3(inputs, source_info, result_info)
            if inputs.identity["layout"] == "social":
                build_social_reel(inputs.source, inputs.result, partial, engine=inputs.job.engine)
            else:
                build_comparison_reel(inputs.source, inputs.result, partial,
                                      engine=inputs.job.engine, layout=inputs.identity["layout"])
            info = ffprobe(partial)
            if (partial.is_symlink() or partial.stat().st_size == 0
                    or info["width"] != 1080 or info["height"] != 1920
                    or info["frames"] != result_info["frames"]
                    or abs(info["fps"] - result_info["fps"]) > 0.001
                    or abs(info["duration"] - result_info["frames"] / result_info["fps"]) > 1 / result_info["fps"]):
                raise ValueError("The reel failed output validation")
            self._verify_inputs(inputs)
            with self._lock:
                os.replace(partial, output)
                published = True
                state.update(status="ready")
                self._write(directory, state)
        except Exception as exc:
            LOG.warning("Reel %s failed (%s)", key[2], type(exc).__name__)
            if published:
                output.unlink(missing_ok=True)
            if isinstance(exc, subprocess.TimeoutExpired):
                error = "Reel creation timed out. Retry to build it again."
            elif isinstance(exc, subprocess.CalledProcessError):
                error = "The local video encoder could not create the reel. Retry to build it again."
            elif isinstance(exc, (ValueError, HTTPException, KeyError)):
                error = "The source or result could not be verified for this reel. Check the take before retrying."
            else:
                error = "Could not create the reel. Retry to build it again."
            with self._lock:
                state.update(status="error", error=error)
                self._write(directory, state)
        finally:
            partial.unlink(missing_ok=True)
            with self._lock:
                self._active.discard(key)

    def media(self, job_id: str, artifact_id: str, download: bool = False) -> FileResponse:
        with self._lock:
            media = Path(self.media_dir()).resolve()
            state = self._read(media, job_id, artifact_id)
            if state["status"] != "ready":
                raise HTTPException(409, "The reel is not ready yet.")
            directory = self._directory(media, job_id, artifact_id)
            return FileResponse(directory / "reel.mp4", media_type="video/mp4",
                                filename=self._public(state)["filename"],
                                content_disposition_type="attachment" if download else "inline")


def create_router(service: ReelService) -> APIRouter:
    router = APIRouter()

    @router.post("/api/jobs/{job_id}/reveal")
    async def create_reveal(job_id: str, layout: str = "wipe", retry: bool = False):
        state = await asyncio.to_thread(service.request, job_id, layout, retry)
        if layout != "social":
            # Legacy callers still get a completed download URL, but no encoder runs in
            # the request thread pool. New social clients always use explicit polling.
            while state["status"] in {"queued", "running"}:
                await asyncio.sleep(0.05)
                state = await asyncio.to_thread(service.status, job_id, state["artifact_id"])
            if state["status"] == "error":
                raise HTTPException(500, state["error"])
            state["reveal_url"] = state["preview_url"]
        return JSONResponse(state, status_code=202 if state["status"] in {"queued", "running"} else 200)

    @router.get("/api/jobs/{job_id}/reels/{artifact_id}")
    def reel_status(job_id: str, artifact_id: str):
        return service.status(job_id, artifact_id)

    @router.get("/api/jobs/{job_id}/reels/{artifact_id}/media")
    def reel_media(job_id: str, artifact_id: str, download: bool = False):
        return service.media(job_id, artifact_id, download)

    @router.get("/api/jobs/{job_id}/reveal")
    def legacy_media(job_id: str, download: bool = False, layout: str = "wipe"):
        inputs = service.inputs(job_id, layout)
        return service.media(job_id, _json_digest(inputs.identity), download)

    return router
