"""Independent H3 Studio API. MVP: one reference and one continuous shot only."""
import asyncio
import shutil
import copy
import json
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
import mimetypes
import core
from api_schema import _public_project_id
from project_scope import submission_project
from continuable_take import get_validated_family
from h3_swap_native import NATIVE_ARTIFACT_RELATION
from h3_capsule import contained, digest_file, frozen_references, get_capsule, replay_inputs
import character_references
from character_library import CharacterLibrary
from h3_graphs import REFERENCE_SLOTS
from h3_recipe import ENGINE, MAX_TEXT, make_recipe
from h3_uploads import save_reference
from source_clip import MAX_CLIP_SECONDS, extract_excerpt, probe_source, require_short_source, validate_selection
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
            'project_id': _public_project_id(job),
            'job': {'id': job.id, 'engine': ENGINE, 'status': job.status,
                    'project_id': _public_project_id(job),
                    'single_shot_only': True, 'parent_job_id': job.meta.get('parent_job_id')},
            'limitations': ['One continuous shot only; no automatic scene splitting or cut rejection.']}


def _dispatch_options(source, references, recipe, media_dir):
    hashes = {'source': digest_file(source)}
    hashes.update({f'reference-{index}': digest_file(path)
                   for index, path in enumerate(references)})
    options = {'recipe': copy.deepcopy(recipe), 'reference_images': list(references),
               'media_dir': media_dir, 'input_hashes': hashes, 'native_capture': True}
    return options


async def _dispatch(dispatch, job, source, references, recipe, media_dir):
    opts = await asyncio.to_thread(_dispatch_options, source, references, recipe, media_dir)
    job.meta['native_capture_requested'] = True
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
        check = self.readiness_check
        report = (await asyncio.to_thread(check) if check is not None else
                  {'ready': False, 'issues': ['Native state capture is not configured on this application.']})
        return {**report, 'limits': {**report.get('limits', {}), 'max_clip_seconds': MAX_CLIP_SECONDS},
                'native_capture_supported': check is not None}

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
        report = await self.readiness()
        if not report.get('ready'):
            raise HTTPException(503, ' '.join(report.get('issues', [])) or 'H3 is not ready')

    async def create_job(self, request: Request, video: UploadFile = File(...),
                         reference_images: list[UploadFile] = File(default=[]),
                         edit_prompt: str = Form(default='', max_length=2000),
                         seed: int = Form(default=302929098223082, ge=0, le=2**64-1),
                         project_id: str | None = Form(default=None),
                         native_capture: bool = Form(default=True),
                         clip_start_seconds: float | None = Form(default=None),
                         clip_end_seconds: float | None = Form(default=None)):
        """Submit one continuous shot and one or two ordered character references.

        MVP processes a selected excerpt (at most 15 seconds) as one shot.
        Both clip_start_seconds and clip_end_seconds are required for longer
        sources; omitting both uses the whole short source. Multi-cut editing is not
        supported or automatically segmented; provide an already isolated shot.
        Automatic cut rejection is deliberately absent (fog/flashes can produce
        false positives). Optional per-reference descriptions are user-owned text injected
        into the frozen prompt scaffold; an empty one is completed by the local vision
        model from that reference image and recorded as generated. Use ordered
        character_descriptions fields, or the single character_description field
        from the studio for the first reference; do not mix both forms. Original audio is
        preserved and conditioned on; output timing is 24fps.
        """
        if native_capture is not True:
            raise HTTPException(422, 'Every new H3 Swap saves its continuation state; native_capture cannot be disabled.')
        media_dir = Path(self.get_media_dir()).resolve()
        origin_project_id = submission_project(project_id, media_dir) if project_id is not None else None
        form = await request.form()
        if ('clip_start_seconds' in form or 'clip_end_seconds' in form) and \
                (clip_start_seconds is None or clip_end_seconds is None):
            raise HTTPException(422, 'Provide both clip_start_seconds and clip_end_seconds')
        # Slot order is the contract: each entry says where that slot's image comes from.
        # Keeping it explicit is what lets slot 1 be a saved character and slot 2 a file.
        declared = [str(item).strip() for item in form.getlist('reference_sources')]
        sources = declared or ['upload'] * len(reference_images)
        if len(sources) != len(declared) and len(sources) != len(reference_images):
            raise HTTPException(422, 'H3 reference list does not match its sources')
        uploads = iter(reference_images)
        slots, reasons = [], []
        for source in sources:
            if source == 'upload':
                upload = next(uploads, None)
                if upload is None:
                    reasons.append('A slot asked for an uploaded file that was not sent.')
                    continue
                slots.append(('upload', upload))
            elif source.startswith('gallery:'):
                job_id = source.split(':', 1)[1].strip()
                paths, why = character_references.resolve([job_id], CharacterLibrary(self.get_media_dir), 1)
                if why:
                    reasons.append(why[0])
                else:
                    slots.append(('gallery', paths[0]))
            else:
                reasons.append(f'Unknown reference source: {source}')
        for upload in uploads:  # older clients send files without a source list
            slots.append(('upload', upload))
        if reasons:
            raise HTTPException(422, ' '.join(reasons))
        total_references = len(slots)
        if not 1 <= total_references <= REFERENCE_SLOTS:
            raise HTTPException(422, f'H3 accepts between 1 and {REFERENCE_SLOTS} reference images')
        # The ordered plural field is canonical. The shipped single-description
        # form (and cached clients) uses the singular alias for reference 1.
        descriptions = form.getlist('character_descriptions')
        legacy_descriptions = form.getlist('character_description')
        if descriptions and legacy_descriptions:
            raise HTTPException(422, 'Use character_descriptions or character_description, not both')
        descriptions = [str(item) for item in (descriptions or legacy_descriptions)]
        if len(descriptions) > len(reference_images):
            raise HTTPException(422, 'H3 reference descriptions must match the ordered reference images')
        if any(len(item) > MAX_TEXT for item in descriptions):
            raise HTTPException(422, 'H3 reference descriptions must be at most 2000 characters')
        suffix = Path(video.filename or '').suffix.lower()
        if suffix not in {'.mp4', '.mov', '.mkv', '.webm'}:
            raise HTTPException(415, 'Use MP4, MOV, MKV or WebM')
        for upload in reference_images:
            if Path(upload.filename or '').suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                raise HTTPException(415, 'Use a PNG, JPEG or WebP reference')
        await self.ready()
        media_dir.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        source = media_dir / f'{job_id}-source{suffix}'
        original = source
        excerpt = media_dir / f'{job_id}-excerpt.mp4'
        references = [media_dir / f'{job_id}-reference-{index + 1}.png'
                      for index in range(total_references)]
        created = []
        try:
            # Reserve only this request's upload paths. A collision must neither
            # overwrite nor later unlink any historical asset, including raw refs.
            for path in [original, *references, *[p.with_suffix('.upload') for p in references]]:
                with path.open('xb'):
                    pass
                created.append(path)
            await save_video(video, original, self.limit)
            info = await asyncio.to_thread(probe_source, original)
            try:
                start, end = validate_selection(info, clip_start_seconds, clip_end_seconds)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            selection = None
            if clip_start_seconds is not None:
                if excerpt.exists():
                    raise ValueError('H3 excerpt destination already exists')
                created.append(excerpt)
                info, selection = await asyncio.to_thread(extract_excerpt, original, excerpt, info, start, end)
                source = excerpt
            if not 1 <= info['duration'] * 24 <= MAX_CLIP_SECONDS * 24:
                raise HTTPException(422, 'H3 source must fit within 1–360 frames at 24fps')
            for (kind, value), destination in zip(slots, references):
                if kind == 'upload':
                    await save_reference(value, destination, self.limit)
                else:
                    await asyncio.to_thread(shutil.copyfile, value, destination)
            recipe = make_recipe(preserve_clip=edit_prompt, seed=seed,
                                 reference_descriptions=tuple(
                                     descriptions + [''] * (len(references) - len(descriptions))),
                                 source_width=info['width'], source_height=info['height'])
            recipe['source_timing'] = copy.deepcopy(info)
            if selection is not None:
                recipe['source_selection'] = selection
            # Validate uploads and selection before lazily creating a Draft.
            if origin_project_id is None:
                origin_project_id = submission_project(None, media_dir)
            job = core.Job(id=job_id, engine=ENGINE, prompt=recipe['effective_prompt'], video=str(source),
                           meta={'origin_project_id': origin_project_id,
                                 'h3_references': [str(path) for path in references],
                                 'h3_reference_origins': [('upload' if kind == 'upload' else 'character')
                                                          for kind, _ in slots],
                                 'h3_recipe': recipe,
                                 'single_shot_only': True, 'source_info': info,
                                 'source_shot_plan': [{'start': 0, 'end': info['frames']-1,
                                                       'fps': info['fps']}]})
            job.meta['h3_original_source'] = str(original)
        except Exception as exc:
            for path in created:
                path.unlink(missing_ok=True)
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(422, 'H3 could not validate the source and reference') from exc
        for path in references:
            path.with_suffix('.upload').unlink(missing_ok=True)
        return await _dispatch(self.dispatch_job, job, source, references, recipe, media_dir)

    def native_state(self, job_id: str):
        """Describe an explicitly captured variant, never manufacture state for an old MP4."""
        job = _load(job_id)
        take_id = job.meta.get('native_take_id')
        if job.status != 'done' or take_id is None:
            return {'available': False}
        try:
            family = get_validated_family(core.WORK, take_id)
            record = family.record
            capsule = record.to_manifest()
            if (record.take_id != take_id or capsule['origin'] !=
                    {'source_job': job.id, 'operator_label': 'native-swap'}):
                raise ValueError('Native variant origin differs')
            context = capsule['family']['context']
            seconds = context['delivered_frames'] / context['fps']
        except (ValueError, OSError, KeyError, TypeError, ZeroDivisionError) as exc:
            raise HTTPException(409, 'The native state could not be verified; the finished Swap is unchanged') from exc
        base = '/api/continuity/takes/' + take_id
        displayed = job.meta.get('processed_frames')
        return {'available': True, 'take_id': take_id,
                'native_seconds': seconds,
                'display_seconds': displayed / 24 if type(displayed) is int and displayed > 0 else None,
                'relation': NATIVE_ARTIFACT_RELATION,
                'urls': {'video': base + '/artifacts/video', 'mctx': base + '/artifacts/mctx',
                         'conditioning': base + '/artifacts/conditioning',
                         'preview': base + '/media', 'capsule': base + '/capsule',
                         'timeline': '/timeline?job_id=' + job.id}}

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

    async def replay(self, job_id: str, payload: dict | None = None):
        media_dir = Path(self.get_media_dir()).resolve()
        native_capture = (payload or {}).get('native_capture', True)
        if native_capture is not True:
            raise HTTPException(422, 'Every H3 re-run saves its continuation state; native_capture must be true.')
        project_id = (payload or {}).get('project_id')
        origin_project_id = submission_project(project_id, media_dir) if project_id is not None else None
        parent = await asyncio.to_thread(_load, job_id)
        try:
            recipe, source, references = await asyncio.to_thread(replay_inputs, parent, media_dir)
            info = await asyncio.to_thread(require_short_source, source)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (KeyError, OSError, TypeError) as exc:
            raise HTTPException(409, 'Frozen H3 recipe or verified local inputs are unavailable or changed') from exc
        await self.ready()
        if origin_project_id is None:
            origin_project_id = submission_project(None, media_dir)
        child = core.Job(id=uuid.uuid4().hex, engine=ENGINE, prompt=recipe['effective_prompt'],
                         video=str(source), meta={'origin_project_id': origin_project_id,
                                                 'h3_references': [str(path) for path in references],
                                                 'h3_recipe': recipe, 'parent_job_id': parent.id,
                                                 'single_shot_only': True,
                                                 'source_info': info,
                                                 'source_shot_plan': [{'start': 0, 'end': info['frames']-1,
                                                                       'fps': info['fps']}]})
        if parent.meta.get('h3_original_source'):
            child.meta['h3_original_source'] = parent.meta['h3_original_source']
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
    router.add_api_route('/api/h3/jobs/{job_id}/native-state', api.native_state, methods=['GET'])
    router.add_api_route('/api/h3/jobs/{job_id}/replay', api.replay, methods=['POST'], status_code=202)
    return router