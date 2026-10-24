"""Explicit immutable image references and parentless attempts, no new worker."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated
import uuid

from fastapi import APIRouter, File, HTTPException, Path as ApiPath, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

import continuity_attempts as attempts
from continuable_take import _directory
from continuity_attempt_api import AttemptRequest
from continuity_root_pipeline import (MAX_REFERENCE_BYTES, resolve_root_references,
                                      root_state, validate_image)

Identifier = Annotated[str, ApiPath(pattern=r'^[0-9a-f]{32}$', min_length=32, max_length=32)]
_PRIVATE = {'Cache-Control': 'private, no-store'}


class RootAttemptRequest(BaseModel):
    """Reuse common attempt validation without extending the anchored mode enum."""
    model_config = ConfigDict(extra='forbid', strict=True)

    request_id: str = Field(pattern=r'^[0-9a-f]{32}$', min_length=32, max_length=32)
    prompt: str = Field(min_length=1, max_length=4000)
    raw_frames: StrictInt = Field(ge=5, le=3600)
    seeds: list[StrictInt] = Field(min_length=1, max_length=attempts.MAX_CANDIDATES)
    reference_ids: list[str] = Field(min_length=1)
    width: StrictInt = Field(ge=32, le=2048)
    height: StrictInt = Field(ge=32, le=2048)

    @model_validator(mode='after')
    def common_contract(self):
        AttemptRequest(request_id=self.request_id, prompt=self.prompt,
                       raw_frames=self.raw_frames, seeds=self.seeds)
        attempts.validate_root_context(self.root_context)
        return self

    @property
    def root_context(self):
        return {'reference_ids': list(self.reference_ids), 'width': self.width, 'height': self.height}


def _store_reference(work, payload):
    """Publish an exclusive immutable PNG, never replace an existing ID."""
    media = _directory(Path(work) / 'media', create=True)
    identifier = uuid.uuid4().hex
    target = media / f'root-reference-{identifier}.png'
    staging = media / f'.root-reference-{uuid.uuid4().hex}.part'
    try:
        descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
        # link is exclusive even on an improbable UUID collision; no replace.
        os.link(staging, target, follow_symlinks=False)
        directory = os.open(media, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        staging.unlink(missing_ok=True)
    return identifier


def create_router(get_work, get_root, *, worker, precheck) -> APIRouter:
    """Share the app's existing attempts Worker; no reconciliation/second queue.

    precheck(root_context, raw_frames, direction) must gate model/reference and
    dependency readiness before any attempt is recorded. It is a read-only
    callback; SDK image uploads/refinement happen later in the shared Worker.
    Local reference uploads only decode/publish images, never call the SDK.
    """
    router = APIRouter(prefix='/api/continuity', tags=['continuity'])

    @router.post('/root-references', status_code=201)
    async def upload(image: UploadFile = File(...)):
        try:
            payload = await image.read(MAX_REFERENCE_BYTES + 1)
            if len(payload) > MAX_REFERENCE_BYTES:
                raise HTTPException(413, 'That image exceeds the 10 MiB limit.')
            try:
                clean = validate_image(payload, image.content_type)
            except ValueError:
                raise HTTPException(422, 'Use a valid, bounded PNG, JPEG or WebP still image.') from None
            try:
                identifier = _store_reference(get_work(), clean)
            except (OSError, ValueError):
                raise HTTPException(503, 'Reference storage is unavailable.') from None
            return JSONResponse({'reference_id': identifier,
                                 'url': f'/api/continuity/root-references/{identifier}'},
                                status_code=201, headers=_PRIVATE)
        finally:
            await image.close()

    @router.get('/root-references/{reference_id}')
    def reference(reference_id: Identifier):
        try:
            paths = resolve_root_references(get_work(),
                {'reference_ids': [reference_id], 'width': 32, 'height': 32})
        except ValueError:
            raise HTTPException(404, 'Unknown reference.') from None
        return FileResponse(paths[0], media_type='image/png', headers=_PRIVATE)

    @router.post('/roots/attempts', status_code=202)
    def start(request: RootAttemptRequest):
        if worker is None or precheck is None:
            raise HTTPException(503, 'New takes are not configured on this instance.')
        context = request.root_context
        try:
            root_state(request.raw_frames)
            resolve_root_references(get_work(), context)
            precheck(request.root_context, request.raw_frames, request.prompt)
        except (OSError, ValueError):
            # Never echo inventory internals, private prompts or filesystem paths.
            raise HTTPException(422, 'The new take could not be prepared. Check its references, length and target readiness.') from None
        try:
            attempt, created = attempts.create_or_get(
                get_root(), take_id=None, mode='root', root_context=context,
                request_id=request.request_id, prompt=request.prompt,
                raw_frames=request.raw_frames, seeds=request.seeds)
        except attempts.AttemptConflict:
            raise HTTPException(409, 'This request identifier already has a different frozen payload.') from None
        except attempts.AttemptError:
            raise HTTPException(422, 'Invalid root attempt.') from None
        except OSError:
            raise HTTPException(503, 'Attempt storage is unavailable.') from None
        if created:
            worker.start(attempt['attempt_id'])
        return JSONResponse(attempts.public(attempt), status_code=202, headers=_PRIVATE)

    @router.get('/roots/attempts/by-request/{request_id}')
    def recover(request_id: Identifier):
        try:
            attempt = attempts.root_by_request(get_root(), request_id)
        except attempts.AttemptNotFound:
            raise HTTPException(404, 'Attempt not found.') from None
        except (attempts.AttemptError, OSError):
            raise HTTPException(503, 'Attempt storage is unavailable.') from None
        return JSONResponse(attempts.public(attempt), headers=_PRIVATE)

    return router
