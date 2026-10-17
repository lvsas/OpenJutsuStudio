"""Stable, path-safe stage artifacts recorded for one local take."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import core


def anchor_entries(job: core.Job) -> list[dict[str, Any]]:
    """Return only valid, media-rooted anchor records in their shot order."""
    entries: list[dict[str, Any]] = []
    for item in job.meta.get("anchors", []):
        if not isinstance(item, dict):
            continue
        filename = item.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename:
            continue
        if not filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        segment = item.get("segment")
        if not isinstance(segment, int) or segment < 0:
            continue
        entries.append({
            "segment": segment, "start": item.get("start"), "end": item.get("end"),
            "source_frame": item.get("source_frame"), "filename": filename,
        })
    return sorted(entries, key=lambda item: item["segment"])


def anchor_path(job: core.Job, segment: int) -> Path | None:
    """Resolve one recorded anchor without accepting a client-provided path."""
    entry = next((item for item in anchor_entries(job) if item["segment"] == segment), None)
    if entry is None:
        return None
    root = (core.WORK / "media").resolve()
    candidate = (root / entry["filename"]).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def public_anchor_frames(job: core.Job) -> list[dict[str, Any]]:
    """Expose descriptive records and stable URLs, never workstation paths."""
    return [
        {key: entry[key] for key in ("segment", "start", "end", "source_frame")}
        | {"url": f"/api/jobs/{job.id}/anchors/{entry['segment']}"}
        for entry in anchor_entries(job)
        if anchor_path(job, entry["segment"]) is not None
    ]