#!/usr/bin/env python3
"""Small, local-first web app for OpenGenjutsu's LTX 2.5 + Ripple pipeline."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

import sys
sys.path.insert(0, str(Path(__file__).parent))
import core

app = FastAPI(title="OpenGenjutsu LTX", version="0.1.0")
MAX_UPLOAD_BYTES = int(os.getenv("OPENGENJUTSU_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
MEDIA_DIR = core.WORK / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="opengenjutsu")
PIPELINE_RUNNER = core.run_pipeline


def _public_job(job: core.Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "step": job.step,
        "progress": job.progress,
        "engine": job.engine,
        "prompt": job.prompt,
        "error": job.error,
        "created": job.created,
        "started": job.started,
        "finished": job.finished,
        "meta": job.meta,
        "result_url": f"/api/jobs/{job.id}/result" if job.status == "done" else None,
    }


def _target_size(width: int, height: int, max_edge: int = 768) -> tuple[int, int]:
    """Fit the source into a 768px long side, rounded to LTX-friendly multiples of 32."""
    scale = min(max_edge / width, max_edge / height)
    w = max(64, round(width * scale / 32) * 32)
    h = max(64, round(height * scale / 32) * 32)
    return w, h


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "ltx25-ripple"}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return PAGE


@app.post("/api/upload-character")
async def upload_character_sheet(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a character sheet image. Returns asset_id for use in job creation."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(415, "Only image uploads are allowed")

    asset_id = uuid.uuid4().hex[:12]
    suffix = Path(file.filename or "ref.png").suffix or ".png"
    dest = MEDIA_DIR / f"char_{asset_id}{suffix}"

    content = await file.read()
    dest.write_bytes(content)

    return {"asset_id": asset_id, "file_path": str(dest), "filename": file.filename}


@app.get("/api/compare")
def compare_frames(job_id: str, segment: int = 0) -> dict[str, Any]:
    """Return source and edited frame paths for side-by-side comparison."""
    try:
        job = core.Job.load(job_id)
    except KeyError:
        raise HTTPException(404, f"Job {job_id} not found")

    # Find source frame for this segment
    source_frame = core.WORK / "media" / f"seg_{segment:03d}_f{job_id}.png"
    if not source_frame.exists():
        # Fallback: look for any segment frame
        candidates = list((core.WORK / "media").glob(f"seg_{segment:03d}_*.png"))
        source_frame = candidates[0] if candidates else None

    # Find edited frame
    edited_frame = None
    if job.result:
        # The result is the final video; edited frame is intermediate
        candidates = list((core.WORK / "media").glob(f"*{job.id}*edited*.png"))
        edited_frame = candidates[0] if candidates else None

    return {
        "job_id": job_id,
        "segment": segment,
        "source_frame": str(source_frame) if source_frame else None,
        "edited_frame": str(edited_frame) if edited_frame else None,
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return [_public_job(j) for j in core.Job.all()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    try:
        return _public_job(core.Job.load(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job introuvable") from exc


@app.post("/api/jobs", status_code=202)
async def create_job(
    video: UploadFile = File(...),
    edit_prompt: str = Form(..., min_length=3, max_length=2000),
    propagation_prompt: str = Form(default=core.RIPPLE_PROMPT, max_length=2000),
    seed: int = Form(default=125348341465200, ge=0),
    ripple_strength: float = Form(default=1.2, ge=0.0, le=2.0),
) -> dict[str, Any]:
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Formats vidéo acceptés : MP4, MOV, MKV, WebM")
    if not edit_prompt.strip():
        raise HTTPException(status_code=422, detail="Décris l'édition à appliquer à la première image.")

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    video_path = MEDIA_DIR / f"{job_id}{suffix}"
    total = 0
    try:
        with video_path.open("wb") as out:
            while chunk := await video.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Vidéo trop volumineuse (limite 500 Mio).")
                out.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="Le fichier vidéo est vide.")
        info = core.ffprobe(video_path)
    except HTTPException:
        video_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        video_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Vidéo illisible : {exc}") from exc
    finally:
        await video.close()

    if info["frames"] < 9:
        video_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="La vidéo doit contenir au moins 9 images.")

    # LTX latent video lengths use 8n+1 frames. Trim only the tail and expose the exact count.
    source_frames = info["frames"]
    frames = ((source_frames - 1) // 8) * 8 + 1
    width, height = _target_size(info["width"], info["height"])
    job = core.Job(
        id=job_id,
        engine="ltx25-ripple",
        prompt=edit_prompt.strip(),
        video=str(video_path),
        meta={
            "source_filename": Path(video.filename or "video").name,
            "source_frames": source_frames,
            "processed_frames": frames,
            "trimmed_tail_frames": source_frames - frames,
            "fps": info["fps"],
            "width": width,
            "height": height,
            "ripple_strength": ripple_strength,
        },
    )
    job.save()
    opts = {
        "edit": {"steps": 4, "seed": seed},
        "ripple_prompt": propagation_prompt.strip() or core.RIPPLE_PROMPT,
        "propagate": {
            "frames": frames,
            "seed": seed,
            "fps": round(info["fps"]),
            "width": width,
            "height": height,
            "steps": 8,
            "strength": ripple_strength,
        },
    }
    loop = asyncio.get_running_loop()
    loop.run_in_executor(_EXECUTOR, PIPELINE_RUNNER, job, video_path, opts)
    return {"job_id": job.id, "status": "queued", "job": _public_job(job)}


def _result_path(result: str) -> Path | None:
    candidate = Path(result)
    options = [candidate] if candidate.is_absolute() else [Path.cwd() / candidate, MEDIA_DIR / candidate]
    options.extend([MEDIA_DIR / Path(result).name, core.WORK / Path(result).name])
    return next((p.resolve() for p in options if p.is_file()), None)


@app.get("/api/jobs/{job_id}/result")
def get_result(job_id: str) -> FileResponse:
    try:
        job = core.Job.load(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job introuvable") from exc
    if job.status != "done" or not job.result:
        raise HTTPException(status_code=409, detail="Le rendu n'est pas encore prêt.")
    path = _result_path(job.result)
    if path is None:
        raise HTTPException(status_code=404, detail="Le fichier de rendu n'a pas été retrouvé sur ce poste.")
    return FileResponse(path, media_type="video/mp4", filename=f"opengenjutsu-{job_id}.mp4")


PAGE = r'''<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenGenjutsu LTX</title>
<style>
:root{color-scheme:dark;--bg:#101319;--panel:#191e27;--line:#303846;--text:#edf2f8;--muted:#aab5c4;--accent:#70d7bd;--bad:#ff8b8b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}main{max-width:920px;margin:0 auto;padding:40px 20px}h1{margin:0;font-size:2rem}p{color:var(--muted)}.card{margin-top:24px;padding:24px;border:1px solid var(--line);border-radius:16px;background:var(--panel)}label{display:block;margin:16px 0 6px;font-weight:650}input,textarea,button{font:inherit}input[type=file],textarea,input[type=number]{width:100%;padding:12px;border-radius:9px;border:1px solid var(--line);background:#11151b;color:var(--text)}textarea{min-height:92px;resize:vertical}button{margin-top:20px;border:0;border-radius:9px;background:var(--accent);color:#06211b;font-weight:750;padding:12px 18px;cursor:pointer}button:disabled{opacity:.55;cursor:wait}.small{font-size:.9rem;color:var(--muted)}.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}.status{margin-top:16px;padding:12px;border:1px solid var(--line);border-radius:10px}.bar{height:8px;background:#0b0e13;border-radius:8px;margin-top:10px;overflow:hidden}.bar i{display:block;height:100%;width:0;background:var(--accent);transition:width .4s}.error{color:var(--bad)}video{width:100%;margin-top:16px;border-radius:12px;background:#000}.link{color:var(--accent)}@media(max-width:650px){.row{grid-template-columns:1fr}main{padding:24px 14px}}
</style></head><body><main>
<h1>OpenGenjutsu <span style="color:var(--accent)">LTX</span></h1>
<p>Édite la première image, puis propage l'édition dans le mouvement d'origine avec LTX 2.5 + Ripple. Le modèle vidéo conserve autant que possible le mouvement et les éléments non modifiés.</p>
<section class="card"><form id="form">
<label for="video">Vidéo source</label><input id="video" name="video" type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska" required>
<label for="edit">Modification à appliquer à l'image de départ</label><textarea id="edit" name="edit_prompt" minlength="3" maxlength="2000" required placeholder="Ex. Remplace uniquement le sac rouge par un sac noir ; conserve la personne, le cadrage et le décor."></textarea>
<label for="prop">Instruction de propagation</label><textarea id="prop" name="propagation_prompt">Use the reference video for motion, timing, camera movement, composition, and unchanged scene content, while consistently propagating the visual edit established in the first frame throughout the video.</textarea>
<div class="row"><div><label for="strength">Force Ripple</label><input id="strength" name="ripple_strength" type="number" min="0" max="2" step="0.05" value="1.2"><div class="small">Commence à 1,2 ; réduire si le changement déborde.</div></div><div><label for="seed">Seed</label><input id="seed" name="seed" type="number" min="0" value="125348341465200"></div></div>
<button id="submit">Lancer l'édition</button><div class="small">Le rendu tourne sur le ComfyUI configuré. Les vidéos de plus de 500 Mio sont refusées.</div>
</form><div id="status" class="status" hidden></div><video id="result" controls hidden></video></section>
<p class="small">Prototype local. LTX 2.5 + Ripple est un pipeline FFAF, pas l'implémentation interne de Genjutsu. Vérifie les licences et conditions des modèles avant tout usage commercial.</p>
</main><script>
const form=document.querySelector('#form'),button=document.querySelector('#submit'),statusBox=document.querySelector('#status'),video=document.querySelector('#result');
let active=null;
function renderStatus(j){statusBox.hidden=false;const labels={queued:'En file d’attente',running:'Génération en cours',done:'Rendu terminé',error:'Échec'};const p=j.status==='done'?100:(j.status==='running'?35:(j.status==='queued'?5:0));statusBox.replaceChildren();const title=document.createElement('strong');title.textContent=(labels[j.status]||j.status)+(j.step?' · '+j.step:'');statusBox.append(title);const bar=document.createElement('div');bar.className='bar';const fill=document.createElement('i');fill.style.width=p+'%';bar.append(fill);statusBox.append(bar);if(j.meta?.trimmed_tail_frames){const note=document.createElement('div');note.className='small';note.textContent=`${j.meta.trimmed_tail_frames} image(s) de fin ignorée(s) pour respecter le format latent vidéo.`;statusBox.append(note)}if(j.error){const err=document.createElement('p');err.className='error';err.textContent=j.error;statusBox.append(err)}if(j.status==='done'&&j.result_url){video.src=j.result_url;video.hidden=false;button.disabled=false;localStorage.removeItem('opengenjutsu_job')}if(j.status==='error'){button.disabled=false;localStorage.removeItem('opengenjutsu_job')}}
async function poll(id){active=id;localStorage.setItem('opengenjutsu_job',id);try{const r=await fetch('/api/jobs/'+encodeURIComponent(id));const j=await r.json();if(!r.ok)throw new Error(j.detail||'Job introuvable');renderStatus(j);if(['done','error'].includes(j.status)){active=null;return}setTimeout(()=>poll(id),2500)}catch(e){statusBox.hidden=false;statusBox.textContent='Erreur de suivi : '+e.message;button.disabled=false;active=null}}
form.addEventListener('submit',async e=>{e.preventDefault();if(active)return;button.disabled=true;video.hidden=true;statusBox.hidden=false;statusBox.textContent='Téléversement et préparation…';try{const data=new FormData(form);const r=await fetch('/api/jobs',{method:'POST',body:data});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Échec de lancement');renderStatus(j.job);poll(j.job_id)}catch(err){statusBox.textContent=err.message;statusBox.className='status error';button.disabled=false}});
const saved=localStorage.getItem('opengenjutsu_job');if(saved)poll(saved);
</script></body></html>'''
