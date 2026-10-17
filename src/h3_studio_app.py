"""Opt-in registration of the isolated H3 Studio routes and page."""
import asyncio
import os
from concurrent.futures import Executor
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def _h3_readiness():
    from h3_graphs import build_h3_recast
    from readiness import check_readiness
    graph = build_h3_recast('validation-video', 'validation-image', 'H3 readiness check',
                            source_frames=5)
    return check_readiness(required_graph=graph)


def _dispatch(executor: Executor, job, source: Path, opts: dict):
    from h3_pipeline import run_h3_pipeline
    return asyncio.get_running_loop().run_in_executor(executor, run_h3_pipeline, job, source, opts)


def register_optional_h3(app: FastAPI, executor: Executor, get_media_dir, max_upload_bytes: int):
    """Register H3 unless the operator explicitly disables it."""
    disabled = os.getenv('OPENGENJUTSU_H3_STUDIO_ENABLED', '1').lower() in {'0', 'false', 'no', 'off'}
    if disabled:
        return False
    from h3_api import create_router
    app.include_router(create_router(
        get_media_dir, max_upload_bytes, _h3_readiness,
        lambda job, source, opts: _dispatch(executor, job, source, opts),
    ))
    template = Path(__file__).parent / 'templates' / 'h3.html'

    @app.get('/h3', response_class=HTMLResponse)
    def h3_studio_page():
        return template.read_text()

    return True
