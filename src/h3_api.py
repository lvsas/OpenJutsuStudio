"""Independent H3 Studio API. MVP: one reference and one continuous shot only."""
import asyncio
import copy
import json
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
import core
from h3_capsule import contained, digest_file, get_capsule, replay_inputs
from h3_recipe import ENGINE, make_recipe
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


def _dispatch(dispatch, job, source, reference, recipe, media_dir):
    opts = {'recipe': copy.deepcopy(recipe), 'reference_image': reference, 'media_dir': media_dir,
            'input_hashes': {'source': digest_file(source), 'reference': digest_file(reference)}}
    job.save()
    try:
        dispatch(job, source, opts)
    except Exception as exc:
        job.status, job.error, job.finished = 'error', 'H3 dispatch failed', time.time()
        job.save()
        raise HTTPException(503, 'H3 worker queue is unavailable') from exc
    return _response(job)


class H3API:
    def __init__(self, get_media_dir, max_upload_bytes, readiness_check, dispatch_job):
        self.get_media_dir = get_media_dir
        self.limit = max_upload_bytes
        self.readiness_check = readiness_check
        self.dispatch_job = dispatch_job

    async def ready(self):
        report = await asyncio.to_thread(self.readiness_check)
        if not report.get('ready'):
            raise HTTPException(503, ' '.join(report.get('issues', [])) or 'H3 is not ready')

    async def create_job(self, request: Request, video: UploadFile = File(...),
                         reference_image: UploadFile = File(...),
                         edit_prompt: str = Form(default='', max_length=2000),
                         seed: int = Form(default=302929098223082, ge=0, le=2**64-1)):
        """Submit one continuous shot and exactly one character reference.

        MVP processes the entire clip as one shot. Multi-cut editing is not
        supported or automatically segmented; provide an already isolated shot.
        Automatic cut rejection is deliberately absent (fog/flashes can produce
        false positives). Original audio is preserved; output timing is 24fps.
        """
        form = await request.form()
        if len(form.getlist('reference_image')) != 1 or form.getlist('reference_images'):
            raise HTTPException(422, 'H3 MVP accepts exactly one reference image')
        suffix = Path(video.filename or '').suffix.lower()
        if suffix not in {'.mp4', '.mov', '.mkv', '.webm'}:
            raise HTTPException(415, 'Use MP4, MOV, MKV or WebM')
        if Path(reference_image.filename or '').suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise HTTPException(415, 'Use a PNG, JPEG or WebP reference')
        await self.ready()
        media_dir = Path(self.get_media_dir()).resolve()
        media_dir.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        source = media_dir / f'{job_id}-source{suffix}'
        reference = media_dir / f'{job_id}-reference.png'
        try:
            info = await save_video(video, source, self.limit)
            if not 1 <= info['duration'] * 24 <= 3592:
                raise HTTPException(422, 'H3 source must fit within 1–3592 frames at 24fps')
            await save_reference(reference_image, reference, self.limit)
            recipe = make_recipe(edit_prompt, seed)
            recipe['source_timing'] = copy.deepcopy(info)
            job = core.Job(id=job_id, engine=ENGINE, prompt=recipe['effective_prompt'], video=str(source),
                           meta={'h3_reference': str(reference), 'h3_recipe': recipe,
                                 'single_shot_only': True, 'source_info': info,
                                 'source_shot_plan': [{'start': 0, 'end': info['frames']-1,
                                                       'fps': info['fps']}]})
        except Exception as exc:
            source.unlink(missing_ok=True)
            reference.unlink(missing_ok=True)
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(422, 'H3 could not validate the source and reference') from exc
        return await asyncio.to_thread(_dispatch, self.dispatch_job, job, source, reference, recipe, media_dir)

    def capsule(self, job_id: str, download: bool = False):
        job = _load(job_id)
        try:
            capsule = get_capsule(job)
            result = contained(job.result, self.get_media_dir())
            if digest_file(result) != capsule['assets']['result']['sha256']:
                raise ValueError('H3 result changed after the capsule was frozen')
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(409, 'The frozen H3 capsule or local result is unavailable or changed') from exc
        if download:
            return Response(json.dumps(capsule, indent=2, ensure_ascii=False), media_type='application/json',
                            headers={'Content-Disposition': f'attachment; filename="h3-take-{job.id}.json"'})
        return capsule

    async def replay(self, job_id: str):
        parent = await asyncio.to_thread(_load, job_id)
        media_dir = Path(self.get_media_dir()).resolve()
        try:
            recipe, source, reference = await asyncio.to_thread(replay_inputs, parent, media_dir)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            raise HTTPException(409, 'Frozen H3 recipe or verified local inputs are unavailable or changed') from exc
        await self.ready()
        child = core.Job(id=uuid.uuid4().hex, engine=ENGINE, prompt=recipe['effective_prompt'],
                         video=str(source), meta={'h3_reference': str(reference), 'h3_recipe': recipe,
                                                 'parent_job_id': parent.id, 'single_shot_only': True})
        return await asyncio.to_thread(_dispatch, self.dispatch_job, child, source, reference, recipe, media_dir)


def create_router(get_media_dir, max_upload_bytes, readiness_check, dispatch_job):
    """readiness_check must be H3-specific; dispatch_job must run run_h3_pipeline.

    Dispatch receives (core.Job, source: Path, opts: dict). Generic job GET/result
    routes can serve these jobs. No LTX checks, worker or frontend are installed.
    """
    api = H3API(get_media_dir, max_upload_bytes, readiness_check, dispatch_job)
    router = APIRouter(tags=['H3 Studio'])
    router.add_api_route('/api/h3/jobs', api.create_job, methods=['POST'], status_code=202)
    router.add_api_route('/api/h3/jobs/{job_id}/capsule', api.capsule, methods=['GET'])
    router.add_api_route('/api/h3/jobs/{job_id}/replay', api.replay, methods=['POST'], status_code=202)
    return router
