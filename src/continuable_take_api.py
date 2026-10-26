"""Read-only native Take metadata/capsule/preview, separate from media placements.

No native record writes, SDK submission or user-controlled filesystem paths.
Media reads may prepare a disposable metadata-stripped preview cache. The root
supplier is evaluated on each request. Registration is an app decision.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Callable, Literal

from fastapi import APIRouter, HTTPException, Path as ApiPath
from fastapi.responses import FileResponse, JSONResponse

from continuable_take import get_take, get_validated_family, list_takes
from continuable_take_preview import prepare_preview, prepare_poster, PreviewUnavailable


TakeId = Annotated[str, ApiPath(pattern=r'^[0-9a-f]{32}$')]
_PRIVATE = {'Cache-Control': 'private, no-store'}


def _entry(record):
    url = '/api/continuity/takes/' + record.take_id
    return {'take': record.to_manifest(), 'media_url': url + '/media',
            'capsule_url': url + '/capsule'}


def _read(function, *args, missing_status=404):
    try:
        return function(*args)
    except FileNotFoundError as exc:
        message = 'Native Take not found' if missing_status == 404 else 'Native Take family is incomplete'
        raise HTTPException(missing_status, message) from exc
    except PreviewUnavailable as exc:
        raise HTTPException(503, 'Safe native Take preview is unavailable') from exc
    except ValueError as exc:
        raise HTTPException(409, 'Native Take integrity could not be verified') from exc
    except OSError as exc:
        raise HTTPException(503, 'Native Take storage is unavailable') from exc


def create_router(get_work_dir: Callable[[], Path]) -> APIRouter:
    """Expose existing immutable Takes only; never import/generate on navigation."""
    router = APIRouter(prefix='/api/continuity/takes', tags=['continuity'])

    @router.get('')
    def listing():
        records = _read(list_takes, get_work_dir(), missing_status=409)
        # The library lists assets; intentional order belongs to the workspace.
        return JSONResponse({'takes': [_entry(record) for record in records]}, headers=_PRIVATE)

    @router.get('/{take_id}')
    def detail(take_id: TakeId):
        record = _read(get_take, get_work_dir(), take_id)
        return JSONResponse(_entry(record), headers=_PRIVATE)

    @router.get('/{take_id}/capsule')
    def capsule(take_id: TakeId, download: bool = False):
        record = _read(get_take, get_work_dir(), take_id)
        document = record.to_manifest()
        # Transport freshness is not part of the hashed, versioned capsule schema.
        document.pop('integrity')
        headers = {**_PRIVATE, 'X-OpenGenjutsu-Integrity': 'frozen-metadata-only'}
        if download:
            headers['Content-Disposition'] = f'attachment; filename="take-{take_id}.capsule.json"'
        return JSONResponse(document, headers=headers)

    @router.get('/{take_id}/artifacts/{role}')
    def artifact(take_id: TakeId, role: Literal['video', 'mctx', 'conditioning']):
        """Explicit private native backup bytes; never an automatic preview download."""
        family = _read(get_validated_family, get_work_dir(), take_id, missing_status=409)
        suffix = {'video': '.mp4', 'mctx': '.mctx.safetensors',
                  'conditioning': '.cond.safetensors'}[role]
        return FileResponse(getattr(family, role), media_type='application/octet-stream',
            filename=f'take-{take_id}{suffix}',
            headers={**_PRIVATE, 'X-Content-Type-Options': 'nosniff'})

    @router.get('/{take_id}/poster')
    def poster(take_id: TakeId):
        work = get_work_dir()
        family = _read(get_validated_family, work, take_id, missing_status=409)
        path = _read(prepare_poster, work, family, missing_status=409)
        return FileResponse(path, media_type='image/jpeg', headers={**_PRIVATE,
            'X-Content-Type-Options': 'nosniff'})

    @router.get('/{take_id}/readiness')
    def readiness(take_id: TakeId):
        work = get_work_dir()
        _read(get_take, work, take_id)
        try:
            family = get_validated_family(work, take_id)
        except (FileNotFoundError, ValueError, OSError):
            return JSONResponse({'verified': False, 'extend': False,
                'duration_options': [], 'reason_code': 'state_unverified',
                'reason': 'The saved state could not be verified. No generation will start.'}, headers=_PRIVATE)
        context = family.record.to_manifest()['family']['context']
        from h3_av_state import (AVStateError, state_from_family,
                                 requested_lengths, FORWARD_HEAD, FPS)
        try:
            state = state_from_family(family)
        except (AVStateError, OSError, ValueError):
            state = None
        if state is None:
            return JSONResponse({'verified': True, 'extend': False, 'duration_options': [],
                'reason_code': 'timing_unavailable',
                'reason': 'The saved audio timing could not be checked. Choose another take; '
                          'the original is unchanged.'}, headers=_PRIVATE)
        from h3_native_boundaries import source_pin, NativeBoundaryError
        try:
            source_pin(state, 'tail', 'before')
        except NativeBoundaryError as exc:
            return JSONResponse({'verified': True, 'extend': False, 'duration_options': [],
                'reason_code': exc.code, 'reason': str(exc)}, headers=_PRIVATE)
        available = context['delivered_frames'] >= 39 and context['fps'] == FPS
        options = [{'raw_frames': raw, 'seconds': (raw - FORWARD_HEAD) / FPS}
                   for raw in requested_lengths(state)] if available else []
        return JSONResponse({'verified': True, 'extend': bool(options),
            'duration_options': options, 'reason_code': None if options else ('geometry_mismatch' if context['fps'] != FPS else 'no_compatible_duration'),
            'reason': None if options else 'Extend needs at least 1.7 s of delivered footage '
                                          'at 24 fps.'}, headers=_PRIVATE)

    @router.get('/{take_id}/media')
    def media(take_id: TakeId, download: bool = False):
        work = get_work_dir()
        _read(get_take, work, take_id)  # Missing identity is 404; missing state is 409.
        family = _read(get_validated_family, work, take_id, missing_status=409)
        preview = _read(prepare_preview, work, family, missing_status=409)
        headers = {**_PRIVATE, 'X-OpenGenjutsu-Media': 'metadata-stripped-preview'}
        return FileResponse(preview, media_type='video/mp4',
            filename=f'take-{take_id}-preview.mp4', headers=headers,
            content_disposition_type='attachment' if download else 'inline')

    return router
