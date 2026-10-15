"""Public job serialization and target sizing."""
from typing import Any
import core

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
