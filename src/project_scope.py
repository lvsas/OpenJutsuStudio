"""Creation scope: validate/freeze before any studio work, never during a GET."""
from pathlib import Path
from fastapi import HTTPException
import core
from timeline_store import TimelineStore, TimelineError
from timeline_store import identifier


def validate_project(work, project_id) -> None:
    try:
        identifier(project_id)
        project = TimelineStore(work, Path(work) / 'media', 1).get_assets(project_id)
        if project.get('archived'):
            raise HTTPException(409, 'Restore this archived project before generating.')
    except TimelineError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except OSError as exc:
        raise HTTPException(503, 'Project storage is unavailable') from exc


def submission_project(project_id, media_dir) -> str:
    if project_id is not None:
        try:
            identifier(project_id)
        except (TimelineError, TypeError, ValueError) as exc:
            raise HTTPException(422, 'Invalid creation project') from exc
    try:
        store = TimelineStore(core.WORK, Path(media_dir), 1)  # Metadata only; no upload through this store.
        project = store.get_assets(project_id) if project_id is not None else store.draft(create=True)
        if project is None:
            raise HTTPException(503, 'Draft creation could not be confirmed')
        if project.get('archived'):
            raise HTTPException(409, 'Restore this archived project before generating.')
        return project['project_id']
    except TimelineError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except OSError as exc:
        raise HTTPException(503, 'Project storage is unavailable') from exc
