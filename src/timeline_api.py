"""Public timeline router. Root suppliers are evaluated lazily, no global WORK."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import re
import tempfile
import threading
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header
from starlette.concurrency import run_in_threadpool

from timeline_export import ExportManager
from timeline_models import CreateProject, EditNativeWorkspace, EditProject, ExportProject, ImportJob, AssociateAsset, RenameProject, DraftRequest
from timeline_store import TimelineError, TimelineStore


async def _read_upload(request: Request, destination: Path, maximum: int) -> int:
    """Stream multipart directly into private staging, before framework spooling.

    Ignore all client filenames. Only one file plus one decimal revision field
    are accepted; cap total envelope/header/field bytes independently of media.
    """
    kind, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary", b"")
    if kind != b"multipart/form-data" or not boundary or len(boundary) > 200:
        raise TimelineError(422, "Expected multipart file and revision")
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > maximum + 65536:
                raise TimelineError(413, "Video exceeds the configured upload limit")
        except ValueError as exc:
            if isinstance(exc, TimelineError):
                raise
            raise TimelineError(422, "Invalid upload length") from exc
    state = {"headers": {}, "header_name": bytearray(), "header_value": bytearray(),
             "header_bytes": 0, "part": None, "seen": set(), "file_bytes": 0,
             "revision": bytearray(), "finished": False, "parts": 0}

    def part_begin():
        state["parts"] += 1
        if state["parts"] > 2:
            raise TimelineError(422, "Only file and revision fields are accepted")
        state["headers"] = {}
        state["part"] = None

    def header_field(data, start, end):
        state["header_name"].extend(data[start:end])
        state["header_bytes"] += end - start
        if state["header_bytes"] > 8192:
            raise TimelineError(422, "Multipart headers are too large")

    def header_value(data, start, end):
        state["header_value"].extend(data[start:end])
        state["header_bytes"] += end - start
        if state["header_bytes"] > 8192:
            raise TimelineError(422, "Multipart headers are too large")

    def header_end():
        name = bytes(state["header_name"]).lower()
        if name in state["headers"]:
            raise TimelineError(422, "Duplicate multipart header")
        state["headers"][name] = bytes(state["header_value"])
        state["header_name"].clear()
        state["header_value"].clear()

    def headers_finished():
        disposition, opts = parse_options_header(state["headers"].get(b"content-disposition", b""))
        name = opts.get(b"name")
        if disposition != b"form-data" or name not in {b"file", b"revision"} or name in state["seen"]:
            raise TimelineError(422, "Only one file and one revision field are accepted")
        if name == b"revision" and b"filename" in opts:
            raise TimelineError(422, "Revision must be a decimal form field")
        state["seen"].add(name)
        state["part"] = name

    with destination.open("xb") as outgoing:
        def part_data(data, start, end):
            if state["part"] == b"file":
                state["file_bytes"] += end - start
                if state["file_bytes"] > maximum:
                    raise TimelineError(413, "Video exceeds the configured upload limit")
                outgoing.write(data[start:end])
            elif state["part"] == b"revision":
                if len(state["revision"]) + end - start > 16:
                    raise TimelineError(422, "Invalid revision")
                state["revision"].extend(data[start:end])
            else:
                raise TimelineError(422, "Malformed multipart upload")

        def finished():
            state["finished"] = True

        parser = MultipartParser(boundary, callbacks={
            "on_part_begin": part_begin, "on_header_field": header_field,
            "on_header_value": header_value, "on_header_end": header_end,
            "on_headers_finished": headers_finished, "on_part_data": part_data, "on_end": finished})
        total = 0
        try:
            async for chunk in request.stream():
                total += len(chunk)
                if total > maximum + 65536:
                    raise TimelineError(413, "Video exceeds the configured upload limit")
                for offset in range(0, len(chunk), 65536):
                    parser.write(chunk[offset:offset + 65536])
            parser.finalize()
        except TimelineError:
            raise
        except Exception as exc:
            raise TimelineError(422, "Malformed multipart upload") from exc
    revision = bytes(state["revision"])
    if (not state["finished"] or state["seen"] != {b"file", b"revision"}
            or not state["file_bytes"] or not re.fullmatch(rb"(?:0|[1-9][0-9]{0,15})", revision)
            or int(revision) > 2**53 - 1):
        raise TimelineError(422, "Expected nonempty video file and nonnegative decimal revision")
    return int(revision)


def create_router(get_work_dir: Callable[[], Path], get_media_dir: Callable[[], Path],
                  max_upload_bytes: int) -> APIRouter:
    """Integration: create_router(lambda: WORK, lambda: MEDIA, MAX_UPLOAD_BYTES)."""
    if type(max_upload_bytes) is not int or max_upload_bytes <= 0:
        raise ValueError("max_upload_bytes must be a positive integer")
    contexts: dict[tuple[str, str], tuple[TimelineStore, ExportManager]] = {}
    guard = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        for _, manager in contexts.values():
            await run_in_threadpool(manager.close)

    router = APIRouter(prefix="/api/timeline", tags=["timeline"], lifespan=lifespan)

    def context() -> tuple[TimelineStore, ExportManager]:
        key = (str(Path(get_work_dir()).resolve()), str(Path(get_media_dir()).resolve()))
        with guard:
            if key not in contexts:
                store = TimelineStore(Path(key[0]), Path(key[1]), max_upload_bytes)
                contexts[key] = (store, ExportManager(store))
            return contexts[key]

    def invoke(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except TimelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Timeline storage is unavailable") from exc

    def store() -> TimelineStore:
        return invoke(context)[0]

    def manager() -> ExportManager:
        return invoke(context)[1]

    def media_response(path: Path, name: str, download: bool) -> FileResponse:
        return FileResponse(path, media_type="video/mp4", filename=name,
                            content_disposition_type="attachment" if download else "inline",
                            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @router.get('/library')
    def common_library():
        return {'jobs': invoke(store().library_jobs)}

    @router.get('/draft')
    def get_draft():
        return {'project': invoke(store().draft)}

    @router.post('/draft')
    def ensure_draft(payload: DraftRequest):
        return {'project': invoke(store().draft, create=True)}

    @router.patch('/projects/{project_id}/name')
    def rename_project(project_id: str, payload: RenameProject):
        return invoke(store().rename, project_id, payload.revision, payload.title)

    @router.get("/projects")
    def list_projects():
        return {"projects": invoke(store().list_projects)}

    @router.post("/projects", status_code=201)
    def create_project(payload: CreateProject):
        return invoke(store().create, payload.title, payload.character_id)

    @router.get("/projects/{project_id}")
    def get_project(project_id: str):
        return invoke(store().get, project_id)

    @router.patch("/projects/{project_id}")
    def edit_project(project_id: str, payload: EditProject):
        return invoke(store().edit, project_id, payload)

    @router.get('/projects/{project_id}/assets')
    def get_project_assets(project_id: str):
        return invoke(store().get_assets, project_id)

    @router.post('/projects/{project_id}/assets')
    def associate_project_asset(project_id: str, payload: AssociateAsset):
        return invoke(store().associate_asset, project_id, payload)

    @router.get("/projects/{project_id}/native-workspace")
    def get_native_workspace(project_id: str):
        return invoke(store().get_native_workspace, project_id)

    @router.patch("/projects/{project_id}/native-workspace")
    def edit_native_workspace(project_id: str, payload: EditNativeWorkspace):
        return invoke(store().edit_native_workspace, project_id, payload)

    @router.post("/projects/{project_id}/clips", status_code=201)
    def import_job(project_id: str, payload: ImportJob):
        return invoke(store().import_job, project_id, payload.revision, payload.job_id)

    @router.post("/projects/{project_id}/imports", status_code=201)
    async def import_upload(project_id: str, request: Request):
        current = store()
        # Check project ID/existence before consuming any upload bytes.
        await run_in_threadpool(invoke, current.get, project_id)
        try:
            with tempfile.TemporaryDirectory(prefix="upload-", dir=current.root / "staging") as temporary:
                path = Path(temporary) / "video.mp4"
                revision = await _read_upload(request, path, max_upload_bytes)
                return await run_in_threadpool(invoke, current.import_upload, project_id, revision, path)
        except TimelineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Upload staging is unavailable") from exc

    @router.get("/takes/{take_id}/media")
    def take_media(take_id: str, download: bool = False):
        return media_response(invoke(store().take_media, take_id), f"take-{take_id}.mp4", download)

    @router.post("/projects/{project_id}/export")
    def export_project(project_id: str, payload: ExportProject):
        result = invoke(manager().submit, project_id, payload.revision)
        code = 202 if result["status"] in {"queued", "running"} else 200
        return JSONResponse(result, status_code=code)

    @router.post("/projects/{project_id}/native-workspace/export")
    def export_native_workspace(project_id: str, payload: ExportProject):
        result = invoke(manager().submit, project_id, payload.revision, source="native")
        code = 202 if result["status"] in {"queued", "running"} else 200
        return JSONResponse(result, status_code=code)

    @router.get("/exports/{export_id}")
    def export_status(export_id: str):
        return invoke(manager().get, export_id)

    @router.get("/exports/{export_id}/media")
    def export_media(export_id: str, download: bool = False):
        return media_response(invoke(manager().media, export_id), f"timeline-{export_id}.mp4", download)

    return router
