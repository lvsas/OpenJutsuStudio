"""A restart must not leave a character job pretending to run.

Submissions live in a background thread. If the process stops between the upload
and the recorded prompt id, nothing will ever complete that job, and the page
polls a status that can never change. On startup, any character job still in a
non-terminal state is closed with a message a person can act on.
"""
from __future__ import annotations

import json
from pathlib import Path

CHARACTER_ENGINE = "flux3-klein-character"
INTERRUPTED = ("queued", "running")
MESSAGE = ("The studio restarted while this character was generating. ComfyUI may still hold "
           "the image, but it is not linked to this job. Run it again.")


def fail_interrupted(work_dir: str | Path) -> list[str]:
    """Mark orphaned character jobs as failed and return the ids that were closed."""
    closed = []
    for path in sorted((Path(work_dir) / "jobs").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or record.get("engine") != CHARACTER_ENGINE:
            continue
        if record.get("status") not in INTERRUPTED:
            continue
        record["status"] = "error"
        record["step"] = "character_interrupted"
        record["error"] = MESSAGE  # the status route surfaces this field, not meta
        meta = record.get("meta")
        if not isinstance(meta, dict):
            record["meta"] = {}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(path)
        closed.append(path.stem)
    return closed
