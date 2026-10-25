"""Public job serialization and target sizing."""
from typing import Any
import re
import core
from take_artifacts import public_anchor_frames

def _public_project_id(job: core.Job) -> str | None:
    """Expose only a frozen, well-formed project identifier; never resolve on GET."""
    value = job.meta.get("origin_project_id") if isinstance(job.meta, dict) else None
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) else None

def _public_job(job: core.Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": _public_project_id(job),
        "status": job.status,
        "step": job.step,
        "progress": job.progress,
        "engine": job.engine,
        "prompt": job.prompt,
        "error": job.error,
        "created": job.created,
        "started": job.started,
        "finished": job.finished,
        "meta": {key: value for key, value in job.meta.items()
                 if key not in {"h3_original_source", "original_source"}},
        "result_url": f"/api/jobs/{job.id}/result" if job.status == "done" else None,
        "source_url": f"/api/jobs/{job.id}/source" if job.video else None,
        "anchor_frames": public_anchor_frames(job),
    }

def _target_size(width: int, height: int, target_megapixels: float = 0.9) -> tuple[int, int]:
    """Preserve aspect ratio at roughly 0.9 MP, aligned to LTX multiples of 32."""
    if width <= 0 or height <= 0:
        raise ValueError("Source dimensions must be positive")
    target_pixels = target_megapixels * 1_000_000
    scale = (target_pixels / (width * height)) ** 0.5
    w = max(64, round(width * scale / 32) * 32)
    h = max(64, round(height * scale / 32) * 32)
    return w, h
