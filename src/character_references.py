"""Turn saved character ids into swap reference paths.

A saved character has already proven itself: the library checked its capsule,
its image size, its digest and its PNG shape. Anything that uses a character as
a reference reuses that proof instead of inventing a second trust path.
"""
from __future__ import annotations

from character_library import LibraryError


def resolve(ids, library, limit: int) -> tuple[list, list[str]]:
    """Return (paths, reasons). One bad id never hides the good ones."""
    paths, reasons, seen = [], [], set()
    for raw in ids or ():
        job_id = str(raw).strip()
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        if len(paths) >= limit:
            reasons.append(f'Only {limit} reference image(s) fit; remove one from the gallery selection.')
            break
        try:
            paths.append(library.completed_image(job_id))
        except LibraryError as error:
            reasons.append(f'{job_id[:8]}: {error}')
    return paths, reasons
