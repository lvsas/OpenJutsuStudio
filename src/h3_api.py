"""Independent H3 Studio API. MVP: one reference and one continuous shot only."""
import asyncio
import copy
import json
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
import mimetypes
import core
from h3_capsule import contained, digest_file, frozen_references, get_capsule, replay_inputs
from h3_graphs import REFERENCE_SLOTS
from h3_recipe import ENGINE, MAX_TEXT, make_recipe
from h3_uploads import save_reference
from uploads import save_video


def _load(job_id):
    try:
        job = core.Job.load(job_id)
    except KeyError as exc:
        raise HTTPException(404, 'H3 job not found') from exc
    if job.engine != ENGINE:
        raise HTTPException(404, 'H3 job not found')
    return job


def _response(job):
    return {'job_id': job.id, 'status': job.status, 'parent_job_id': job.meta.get('parent_job_id'),
            'job': {'id': job.id, 'engine': ENGINE, 'status': job.status,
                    'single_shot_only': True, 'parent_job_id': job.meta.get('parent_job_id')},
            'limitations': ['One continuous shot only; no automatic scene splitting or cut rejection.']}


def _dispatch_options(source, references, recipe, media_dir):
    hashes = {'source': digest_file(source)}
    hashes.update({f'reference-{index}': digest_file(path)
                   for index, path in enumerate(references)})
    return {'recipe': copy.deepcopy(recipe), 'reference_images': list(references),
            'media_dir': media_dir, 'input_hashes': hashes}


async def _dispatch(dispatch, job, source, references, recipe, media_dir):
    opts = await asyncio.to_thread(_dispatch_options, source, references, recipe, media_dir)
    await asyncio.to_thread(job.save)
    try:
        # Call dispatch on the ASGI loop: app adapters use run_in_executor here.
        dispatch(job, source, opts)
    except Exception as exc:
        job.status, job.error, job.finished = 'error', 'H3 dispatch failed', time.time()
        await asyncio.to_thread(job.save)
        raise HTTPException(503, 'H3 worker queue is unavailable') from exc
    return _response(job)


class H3API:
    def __init__(self, get_media_dir, max_upload_bytes, readiness_check, dispatch_job):
        self.get_media_dir = get_media_dir
        self.limit = max_upload_bytes
        self.readiness_check = readiness_check
        self.dispatch_job = dispatch_job

    async def readiness(self):
        return await asyncio.to_thread(self.readiness_check)

    def _asset(self, job_id, field, media_type, index=0):
        job = _load(job_id)
        try:
            if field == 'source':
                path = contained(job.video, self.get_media_dir())
            else:
                path = contained(frozen_references(job)[index], self.get_media_dir())
        except (IndexError, KeyError, ValueError, OSError) as exc:
            raise HTTPException(404, f'H3 {field} asset is unavailable') from exc
        return FileResponse(path, media_type=media_type or mimetypes.guess_type(path.name)[0])

    def source(self, job_id):
        return self._asset(job_id, 'source', None)

    def reference(self, job_id, index: int = 0):
        return self._asset(job_id, 'reference', 'image/png', index)

    async def ready(self):
        report = await asyncio.to_thread(self.readiness_check)
        if not report.get('ready'):
            raise HTTPException(503, ' '.join(report.get('issues', [])) or 'H3 is not ready')

    async def create_job(self, request: Request, video: UploadFile = File(...),
                         reference_images: list[UploadFile] = File(...),
                         edit_prompt: str = Form(default='', max_length=2000),
                         seed: int = Form(default=302929098223082, ge=0, le=2**64-1)):
        """Submit one continuous shot and one or two ordered character references.

        MVP processes the entire clip as one shot. Multi-cut editing is not
        supported or automatically segmented; provide an already isolated shot.
        Automatic cut rejection is deliberately absent (fog/flashes can produce
        false positives). Optional per-reference descriptions are user-owned text injected
        into the frozen prompt scaffold; an empty one is completed by the local vision
        model from that reference image and recorded as generated. Original audio is
        preserved and conditioned on; output timing is 24fps.
        """
        form = await request.form()
        if not 1 <= len(form.getlist('reference_images')) <= REFERENCE_SLOTS:
            raise HTTPException(422, f'H3 accepts between 1 and {REFERENCE_SLOTS} reference images')
        descriptions = [str(item) for item in form.getlist('character_descriptions')][:REFERENCE_SLOTS]
        if any(len(item) > MAX_TEXT for item in descriptions):
            raise HTTPException(422, 'H3 reference descriptions must be at most 2000 characters')
        suffix = Path(video.filename or '').suffix.lower()
        if suffix not in {'.mp4', '.mov', '.mkv', '.webm'}:
            raise HTTPException(415, 'Use MP4, MOV, MKV or WebM')
        for upload in reference_images:
            if Path(upload.filename or '').suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                raise HTTPException(415, 'Use a PNG, JPEG or WebP reference')
        await self.ready()
        media_dir = Path(self.get_media_dir()).resolve()
        media_dir.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        source = media_dir / f'{job_id}-source{suffix}'
        references = [media_dir / f'{job_id}-reference-{index + 1}.png'
                      for index in range(len(reference_images))]
        try:
            info = await save_video(video, source, self.limit)
            if not 1 <= info['duration'] * 24 <= 3592:
                raise HTTPException(422, 'H3 source must fit within 1–3592 frames at 24fps')
            for upload, destination in zip(reference_images, references):
                await save_reference(upload, destination, self.limit)
            recipe = make_recipe(preserve_clip=edit_prompt, seed=seed,
                                 reference_descriptions=tuple(
                                     descriptions + [''] * (len(references) - len(descriptions))),
                                 source_width=info['width'], source_height=info['height'])
            recipe['source_timing'] = copy.deepcopy(info)
            job = core.Job(id=job_id, engine=ENGINE, prompt=recipe['effective_prompt'], video=str(source),
                           meta={'h3_references': [str(path) for path in references], 'h3_recipe': recipe,
                                 'single_shot_only': True, 'source_info': info,
                                 'source_shot_plan': [{'start': 0, 'end': info['frames']-1,
                                                       'fps': info['fps']}]})
        except Exception as exc:
            source.unlink(missing_ok=True)
            for path in references:
                path.unlink(missing_ok=True)
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(422, 'H3 could not validate the source and reference') from exc
        return await _dispatch(self.dispatch_job, job, source, references, recipe, media_dir)

    def capsule(self, job_id: str, download: bool = False):
        job = _load(job_id)
        try:
            capsule = get_capsule(job)
            result = contained(job.result, self.get_media_dir())
            if digest_file(result) != capsule['assets']['result']['sha256']:
                raise ValueError('H3 result changed after the capsule was frozen')
        except ValueError as exc:
            # Our own messages are path-free and are the actionable reason.
            raise HTTPException(409, str(exc)) from exc
        except (KeyError, OSError) as exc:
            raise HTTPException(409, 'The frozen H3 capsule or local result is unavailable or changed') from exc
        if download:
            return Response(json.dumps(capsule, indent=2, ensure_ascii=False), media_type='application/json',
                            headers={'Content-Disposition': f'attachment; filename="h3-take-{job.id}.json"'})
        return capsule

    async def replay(self, job_id: str):
        parent = await asyncio.to_thread(_load, job_id)
        media_dir = Path(self.get_media_dir()).resolve()
        try:
            recipe, source, references = await asyncio.to_thread(replay_inputs, parent, media_dir)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (KeyError, OSError, TypeError) as exc:
            raise HTTPException(409, 'Frozen H3 recipe or verified local inputs are unavailable or changed') from exc
        await self.ready()
        child = core.Job(id=uuid.uuid4().hex, engine=ENGINE, prompt=recipe['effective_prompt'],
                         video=str(source), meta={'h3_references': [str(path) for path in references],
                                                 'h3_recipe': recipe, 'parent_job_id': parent.id,
                                                 'single_shot_only': True})
        return await _dispatch(self.dispatch_job, child, source, references, recipe, media_dir)


def create_router(get_media_dir, max_upload_bytes, readiness_check, dispatch_job):
    """readiness_check must be H3-specific; dispatch_job must run run_h3_pipeline.

    Dispatch receives (core.Job, source: Path, opts: dict). Generic job GET/result
    routes can serve these jobs. No LTX checks, worker or frontend are installed.
    """
    api = H3API(get_media_dir, max_upload_bytes, readiness_check, dispatch_job)
    router = APIRouter(tags=['H3 Studio'])
    router.add_api_route('/api/h3/readiness', api.readiness, methods=['GET'])
    router.add_api_route('/api/h3/jobs', api.create_job, methods=['POST'], status_code=202)
    router.add_api_route('/api/h3/jobs/{job_id}/source', api.source, methods=['GET'])
    router.add_api_route('/api/h3/jobs/{job_id}/reference', api.reference, methods=['GET'])
    router.add_api_route('/api/h3/jobs/{job_id}/reference/{index}', api.reference, methods=['GET'])
    router.add_api_route('/api/h3/jobs/{job_id}/capsule', api.capsule, methods=['GET'])
    router.add_api_route('/api/h3/jobs/{job_id}/replay', api.replay, methods=['POST'], status_code=202)
    return router