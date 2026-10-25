"""Settings HTTP boundary: no secrets in responses or exception details."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from compute_settings import SettingsError, Store


def _public_response(data):
    return JSONResponse(data, headers={'Cache-Control': 'no-store'})


def _same_origin(request):
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Open settings from this application.')
    if origin:
        expected = urlsplit(str(request.base_url))
        actual = urlsplit(origin)
        if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
            raise HTTPException(403, 'Open settings from this application.')


async def _payload(request, saving=False):
    _same_origin(request)
    body = await request.body()
    if len(body) > 16384:
        raise HTTPException(413, 'Settings payload is too large.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    try:
        data = json.loads(body, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise HTTPException(422, 'Invalid settings JSON.') from None
    allowed = {'base_url', 'api_key', 'clear_api_key', 'model_bindings'} | ({'revision'} if saving else set())
    if not isinstance(data, dict) or set(data)-allowed or 'base_url' not in data:
        raise HTTPException(422, 'Invalid settings fields.')
    if saving and (type(data.get('revision')) is not int or data['revision'] < 0):
        raise HTTPException(422, 'A valid settings revision is required.')
    if 'api_key' in data and not isinstance(data['api_key'], str):
        raise HTTPException(422, 'Invalid API key format.')
    if type(data.get('clear_api_key', False)) is not bool:
        raise HTTPException(422, 'Invalid credential removal flag.')
    if 'model_bindings' in data and not isinstance(data['model_bindings'], dict):
        raise HTTPException(422, 'Invalid model bindings.')
    return data


def create_router(get_work, activity, probe):
    router = APIRouter(tags=['Compute settings'])
    def store():
        return Store(get_work())

    def public(target):
        from model_catalog import roles
        return target.public() | {'model_roles': roles()}

    @router.get('/settings', response_class=HTMLResponse)
    def page():
        return (Path(__file__).parent/'templates'/'settings.html').read_text()

    @router.get('/api/settings/compute')
    def current():
        try:
            return _public_response(public(store().current()))
        except SettingsError as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @router.put('/api/settings/compute')
    async def save(request: Request):
        data = await _payload(request, saving=True)
        def apply():
            with activity.guard():
                target = store().save(data['revision'], data['base_url'],
                                      data.get('api_key'), data.get('clear_api_key', False), data.get('model_bindings'))
                return public(target)
        try:
            return _public_response(await asyncio.to_thread(apply))
        except SettingsError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError:
            raise HTTPException(503, 'Settings save could not be confirmed. Reload before retrying; no generation was submitted.') from None

    @router.post('/api/settings/compute/test')
    async def test(request: Request):
        data = await _payload(request)
        try:
            candidate = store().candidate(data['base_url'], data.get('api_key'), data.get('clear_api_key', False), data.get('model_bindings'))
            return _public_response(await asyncio.to_thread(probe, candidate))
        except SettingsError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except Exception:
            raise HTTPException(503, 'The connection check failed. No settings were saved and no generation was submitted.') from None

    return router
