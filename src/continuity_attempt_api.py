"""HTTP surface for bounded seed attempts over the proven forward chain."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path as ApiPath
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

import continuity_attempts as attempts
from continuable_take_api import TakeId

ATTEMPT_ID = r'^[0-9a-f]{32}$'
RequestId = Annotated[str, ApiPath(pattern=ATTEMPT_ID, min_length=32, max_length=32)]
_PRIVATE = {'Cache-Control': 'private, no-store'}


class AttemptRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    request_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    prompt: str = Field(min_length=1, max_length=4000)
    raw_frames: StrictInt = Field(ge=5, le=3600)
    seeds: list[StrictInt] = Field(min_length=1, max_length=attempts.MAX_CANDIDATES)

    @field_validator('prompt')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('A direction is required.')
        return value

    @field_validator('raw_frames')
    @classmethod
    def grid(cls, value: int) -> int:
        if (value - 5) % 17:
            raise ValueError('H3 frames must follow the native 17k+5 grid.')
        return value

    @field_validator('seeds')
    @classmethod
    def distinct(cls, value: list[int]):
        if any(seed < 0 or seed >= 2 ** 64 for seed in value):
            raise ValueError('Seeds must be below 2^64.')
        if len(set(value)) != len(value):
            raise ValueError('Each candidate needs a distinct seed.')
        return value


def create_router(get_root, *, worker=None, create=None, precheck=None) -> APIRouter:
    """Only a newly persisted request queues work; recovery routes are read-only.

    The optional creation hook follows create_or_get's (record, created) contract.
    """
    @asynccontextmanager
    async def lifespan(app):
        reconcile = getattr(worker, 'reconcile', None)
        if reconcile is not None:
            reconcile()
        yield

    router = APIRouter(prefix='/api/continuity', tags=['continuity'], lifespan=lifespan)

    @router.post('/takes/{take_id}/attempts', status_code=202)
    def start(take_id: TakeId, request: AttemptRequest):
        if worker is None:
            raise HTTPException(503, 'Variants are not configured on this instance.')
        try:
            # Refuse a request that would freeze an uncontinuable take, before a
            # job exists: the check reads saved state and costs no GPU work.
            if precheck is not None:
                try:
                    precheck(take_id, request.raw_frames)
                except ValueError as error:
                    raise HTTPException(422, str(error)) from None
            attempt, created = (create or attempts.create_or_get)(
                get_root(), take_id=take_id, request_id=request.request_id, prompt=request.prompt,
                raw_frames=request.raw_frames, seeds=request.seeds)
        except attempts.AttemptConflict as error:
            raise HTTPException(409, str(error)) from None
        except attempts.AttemptError as error:
            raise HTTPException(422, str(error)) from None
        if created:
            worker.start(attempt['attempt_id'])
        return JSONResponse(attempts.public(attempt), status_code=202, headers=_PRIVATE)

    @router.get('/takes/{take_id}/attempts/by-request/{request_id}')
    def recover(take_id: TakeId, request_id: RequestId):
        try:
            attempt = attempts.by_request(get_root(), take_id, request_id)
        except attempts.AttemptNotFound as error:
            raise HTTPException(404, str(error)) from None
        except (attempts.AttemptError, OSError) as error:
            raise HTTPException(503, 'Attempt storage is unavailable.') from error
        return JSONResponse(attempts.public(attempt), headers=_PRIVATE)

    @router.get('/takes/{take_id}/attempts')
    def listing(take_id: TakeId):
        try:
            records = attempts.list_for_take(get_root(), take_id)
        except (attempts.AttemptError, OSError) as error:
            raise HTTPException(503, 'Attempt storage is unavailable.') from error
        return JSONResponse({'attempts': [attempts.public(a) for a in records[:50]],
                             'total': len(records), 'has_more': len(records) > 50}, headers=_PRIVATE)

    @router.get('/attempts/{attempt_id}')
    def status(attempt_id: str):
        if not attempts.re.fullmatch(ATTEMPT_ID, attempt_id):
            raise HTTPException(422, 'A valid attempt identifier is required.')
        try:
            return attempts.public(attempts.load(get_root(), attempt_id))
        except attempts.AttemptError as error:
            raise HTTPException(404, str(error)) from None

    return router
