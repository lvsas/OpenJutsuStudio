"""Compatibility facade and job orchestration for the local video editor.

Graph construction, media helpers and Comfy transport live in focused modules.
"""
from __future__ import annotations
import json
import time
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from config import WORK, COMFY_BASE_URL, RIPPLE_PROMPT
from graphs import build_frame_edit, build_ripple
from engines import ENGINES, Engine, LTXRippleEngine, MiniMaxH3Engine
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
        return WORK / "jobs" / f"{self.id}.json"

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(self), indent=1))

    @staticmethod
    def load(job_id: str) -> "Job":
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
        segments = detect_scenes(video_path)
        if not segments:
            raise ValueError("no scenes detected")

        # 2. create client
        client = make_client()

        # 3. edit each segment
        edited_segments = []
        total = len(segments)
        for i, seg in enumerate(segments):
            job.step = f"edit_segment_{i + 1}/{total}"
            job.progress = 0.05 + (0.9 * i / total)
            job.save()
            # Remove 'prompt' from opts to avoid duplicate argument
            seg_opts = {k: v for k, v in opts.items() if k != "prompt"}
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

        job.result, job.status, job.step, job.progress = result, "done", "done", 1.0
    except Exception as e:  # noqa: BLE001 - surface any engine failure to the UI
        job.status, job.error = "error", f"{type(e).__name__}: {e}"
    finally:
        job.finished = time.time()
        job.save()
        if client is not None:
            client.close()
