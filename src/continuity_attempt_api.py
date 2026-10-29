"""HTTP surface for bounded seed attempts with frozen native anchor intent."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path as ApiPath
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

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
    mode: Literal['forward', 'prepend', 'bridge'] = 'forward'
    reference_ids: list[str] | None = None
    project_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$', min_length=32, max_length=32)
    second_take_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$',
                                       min_length=32, max_length=32)

    @model_validator(mode='after')
    def anchors(self):
        # The distinctness check needs the path Take and runs before any hook.
        attempts._validate_anchors(None, mode=self.mode, second_take_id=self.second_take_id)
        if self.reference_ids is not None:
            attempts.validate_reference_ids(self.reference_ids)
        return self

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
            raise ValueError('Seeds must be whole numbers from 0 to 2^64-1 (uint64).')
        if len(set(value)) != len(value):
            raise ValueError('Each candidate needs a distinct seed.')
        return value


def create_router(get_root, *, worker=None, create=None, precheck=None,
                  anchored_precheck=None, get_work=None) -> APIRouter:
    """Only a newly persisted request queues work; recovery routes are read-only.

    The optional creation hook follows create_or_get's (record, created) contract.
    Forward uses legacy positional precheck/callbacks. Other modes use
    anchored_precheck(take_id, raw_frames, *, mode, second_take_id).
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
        try:
            attempts._validate_anchors(take_id, mode=request.mode,
                                       second_take_id=request.second_take_id)
        except attempts.AttemptError as error:
            raise HTTPException(422, str(error)) from None
        if worker is None:
            raise HTTPException(503, 'Variants are not configured on this instance.')
        if request.project_id is not None:
            if get_work is None:
                raise HTTPException(503, 'Project-scoped attempts are not configured.')
            from project_scope import validate_project
            validate_project(get_work(), request.project_id)
        anchors = ({} if request.mode == 'forward' else
                   {'mode': request.mode, 'second_take_id': request.second_take_id})
        if request.reference_ids is not None:
            anchors['reference_ids'] = request.reference_ids
        try:
            # Refuse a request that would freeze an uncontinuable take, before a
            # job exists: the check reads saved state and costs no GPU work.
            check = precheck if request.mode == 'forward' and request.reference_ids is None else anchored_precheck
            if check is not None:
                try:
                    audio_context = check(take_id, request.raw_frames, **anchors)
                    if audio_context is not None:
                        from h3_source_audio import validate_audio_context
                        anchors['frozen_audio_context'] = validate_audio_context(audio_context)
                except ValueError as error:
                    raise HTTPException(422, str(error)) from None
                except OSError:
                    # This read-only check precedes persistence and queueing, so
                    # refusal is certain. Never apply it to creation errors,
                    # whose outcome may be unknown, or expose private paths.
                    raise HTTPException(422, 'The saved anchor could not be read. '
                                        'Select an available saved take and try again. '
                                        'No generation was created.') from None
            attempt, created = (create or attempts.create_or_get)(
                get_root(), take_id=take_id, request_id=request.request_id, prompt=request.prompt,
                raw_frames=request.raw_frames, seeds=request.seeds, **anchors,
                **({'project_id': request.project_id} if request.project_id is not None else {}))
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
