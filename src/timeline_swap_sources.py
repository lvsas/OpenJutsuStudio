"""Read-only bindings for completed application Swap results, not native capsules.

Placement UUIDs identify application jobs for source_kind='swap'. Native linkage
is optional metadata and never upgrades a Swap result's continuity capabilities.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

SWAP_ENGINES = ('minimax-h3', 'ltx25-ripple')


def placement_asset_key(placement: dict) -> str:
    """Keep historical native snapshot keys, namespace application-job sources."""
    return ('swap:' if placement.get('source_kind', 'native') == 'swap' else '') + placement['take_id']


def swap_source(store, job_id: str, expected: dict | None = None) -> tuple[Path, dict]:
    """Validate job identity/state and a nonempty confined result, without probing.

    Export bindings include a digest of the resolved result route so retargeting
    a job to an identical hardlink still fails. No private pathname is projected.
    """
    from timeline_store import TimelineError, identifier
    try:
        identifier(job_id)
        manifest = store.work / 'jobs' / (job_id + '.json')
        if manifest.is_symlink() or manifest.parent.is_symlink():
            raise TimelineError(422, 'Swap job storage is unavailable')
        job = store._job(job_id)
        if job.engine not in SWAP_ENGINES or job.status != 'done' or not isinstance(job.result, str) or not job.result:
            raise TimelineError(422, 'Only completed H3 or LTX Swap video jobs can be placed')
        source = Path(job.result)
        if not source.is_absolute():
            # Current jobs use absolute results. Support media-relative historical
            # records and the existing importer convention for cwd-relative paths.
            relative = store.media / source
            source = relative if relative.exists() or len(source.parts) == 1 else source.absolute()
        if any(part.is_symlink() for part in (source, *source.parents)):
            raise TimelineError(422, 'Swap result must not traverse symlinks')
        path = store._source(source, store.media)
        if path.stat().st_size == 0:
            raise TimelineError(422, 'Swap result must be a nonempty regular video file')
        binding = {'source_kind': 'swap', 'job_id': job_id, 'engine': job.engine,
                   'result_path_sha256': hashlib.sha256(str(path.relative_to(store.media)).encode()).hexdigest()}
        if expected is not None and any(expected.get(key) != value for key, value in binding.items()):
            raise TimelineError(409, 'Snapshot Swap result changed')
        return path, binding
    except (TimelineError, OSError, ValueError, RuntimeError) as exc:
        if expected is not None:
            raise TimelineError(409, 'Snapshot Swap result is missing or changed') from exc
        if isinstance(exc, TimelineError):
            raise
        raise TimelineError(422, 'Swap result is unavailable or unsafe') from exc


def freeze_swap_asset(store, job_id: str) -> dict:
    """Freeze exact decoded media, then recheck the application job binding."""
    from timeline_store import TimelineError, digest_file, inspect_mp4
    path, binding = swap_source(store, job_id)
    before = digest_file(path)
    media = inspect_mp4(path)
    current, _ = swap_source(store, job_id, binding)
    if current != path or digest_file(current) != before:
        raise TimelineError(409, 'Swap video changed during validation')
    return {**binding, **media, 'sha256': before[0], 'size_bytes': before[1],
            'identity': list(before[2])}


def native_take_link(store, job) -> dict:
    """Validate a frozen capsule's job linkage, not its media or capability.

    Only bounded metadata is read: no ffprobe, hashing media, imports, or writes.
    A missing/corrupt/misbound capsule simply has no optional library linkage.
    """
    from continuable_take import get_take
    from timeline_store import identifier
    if job.engine not in SWAP_ENGINES or job.status != 'done' or not isinstance(job.meta, dict):
        return {}
    try:
        take_id = identifier(job.meta.get('native_take_id'))
        record = get_take(store.work, take_id)
        if record.to_manifest()['origin']['source_job'] == job.id:
            return {'native_take_id': take_id}
    except (ValueError, OSError, KeyError, TypeError):
        pass
    return {}
