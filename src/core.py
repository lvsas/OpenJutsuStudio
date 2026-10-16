"""Compatibility facade and job orchestration for the local video editor.

Graph construction, media helpers and Comfy transport live in focused modules.
"""
from __future__ import annotations
import json
import re
import uuid
import time
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from config import WORK, COMFY_BASE_URL, RIPPLE_PROMPT
from graphs import build_frame_edit, build_ripple
from engines import ENGINES, Engine, LTXRippleEngine
from comfy_transport import make_client, _run_graph, _graph_to_workflow
from media import (detect_scenes, ffprobe, extract_first_frame,
                   extract_segment_frames, merge_segments, has_ffmpeg, upscale_video)

def edit_segment(video_path: str | Path, segment: dict, prompt: str,
                 client=None, engine=None, **opts) -> str:
    """Run one inclusive shot, keeping asset transfer and frame counts explicit."""
    from segments import render_segment
    owned = client is None
    client = client if client is not None else make_client()
    try:
        return render_segment(video_path, segment, prompt, client,
                              engine if engine is not None else ENGINES["ltx25-ripple"],
                              WORK, **opts)
    finally:
        if owned:
            client.close()


@dataclass
class Job:
    id: str
    status: str = "queued"          # queued | running | done | error
    step: str = ""
    progress: float = 0.0
    engine: str = "ltx25-ripple"
    prompt: str = ""
    video: str = ""
    result: str | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.id):
            raise ValueError("Invalid job identifier")
        return WORK / "jobs" / f"{self.id}.json"

    def save(self):
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(asdict(self), indent=1))
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def load(job_id: str) -> "Job":
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise KeyError(job_id)
        p = WORK / "jobs" / f"{job_id}.json"
        if not p.exists():
            raise KeyError(job_id)
        return Job(**json.loads(p.read_text()))

    @staticmethod
    def all() -> list["Job"]:
        js = []
        for p in sorted((WORK / "jobs").glob("*.json"), reverse=True):
            try:
                js.append(Job(**json.loads(p.read_text())))
            except Exception:
                continue
        return js


_SEGMENT_BOUNDARY_FRACTIONS = {
    "prepare_segment": 0.0,
    "edit_frame_submitting": 0.08,
    "edit_frame_downloaded": 0.28,
    "propagate_submitting": 0.34,
    "propagate_downloaded": 0.86,
    "trim_segment": 0.92,
}


def _record_segment_progress(job: Job, index: int, total: int, stage: str) -> None:
    """Persist only real, ordered pipeline boundaries for the active segment."""
    fraction = _SEGMENT_BOUNDARY_FRACTIONS.get(stage)
    if fraction is None:
        return
    segment_start = 0.05 + (0.85 * index / total)
    segment_end = 0.05 + (0.85 * (index + 1) / total)
    job.step = f"{stage}_{index + 1}/{total}"
    job.progress = segment_start + ((segment_end - segment_start) * fraction)
    job.save()


def run_pipeline(job: Job, video_path: Path, opts: dict) -> None:
    """Multi-segment pipeline: detect cuts → edit each segment → merge.
    Runs in a worker thread."""
    engine = ENGINES.get(job.engine)
    if engine is None:
        job.status, job.error = "error", f"unknown engine {job.engine}"
        job.finished = time.time()
        job.save()
        return

    client = None
    job.status, job.started, job.step = "running", time.time(), "init"
    job.save()

    try:
        # 1. detect scene cuts (no client needed)
        job.step, job.progress = "detect_scenes", 0.02
        job.save()
        segments = opts.get("shots") or detect_scenes(video_path)
        if not segments:
            raise ValueError("no scenes detected")

        from segments import latent_frames
        job.meta["shots"] = [
            {**shot, "source_frames": shot["end"] - shot["start"] + 1,
             "inference_frames": latent_frames(shot["end"] - shot["start"] + 1),
             "padding_frames": latent_frames(shot["end"] - shot["start"] + 1)
                               - (shot["end"] - shot["start"] + 1)}
            for shot in segments
        ]
        job.save()
        # 2. create client
        client = make_client()

        # 3. edit each segment
        edited_segments = []
        total = len(segments)
        for i, seg in enumerate(segments):
            _record_segment_progress(job, i, total, "prepare_segment")
            # Remove 'prompt' from opts to avoid duplicate argument.
            seg_opts = {k: v for k, v in opts.items() if k != "prompt"}
            seg_opts["on_progress"] = lambda stage, i=i: _record_segment_progress(job, i, total, stage)
            result = edit_segment(
                video_path=video_path,
                segment=seg,
                prompt=job.prompt,
                client=client,
                engine=engine,
                **seg_opts
            )
            edited_segments.append(result)

        # 4. merge segments
        job.step, job.progress = "merge_segments", 0.95
        job.save()
        if len(edited_segments) == 1:
            result = edited_segments[0]
        else:
            result = merge_segments(edited_segments)

        # 5. upscale (optional)
        if opts.get("upscale", False):
            job.step, job.progress = "upscale", 0.98
            job.save()
            result = upscale_video(result, scale=opts.get("upscale_scale", 2.0))

        if result is None:
            raise RuntimeError("Pipeline produced no output video")
        if opts.get("preserve_audio", False):
            from output_media import restore_source_audio
            result = restore_source_audio(result, str(video_path), WORK / "media" / f"final_{job.id}.mp4")
        job.result, job.status, job.step, job.progress = result, "done", "done", 1.0
        from take_capsule_api import freeze_take_capsule
        freeze_take_capsule(job, Path(result))
    except Exception as e:  # noqa: BLE001 - surface any engine failure to the UI
        job.status, job.error = "error", f"{type(e).__name__}: {e}"
    finally:
        job.finished = time.time()
        job.save()
        if client is not None:
            client.close()
