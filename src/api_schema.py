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
        "source_url": f"/api/jobs/{job.id}/source" if job.video else None,
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
