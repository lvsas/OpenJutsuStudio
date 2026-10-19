"""Opt-in registration for the Character API and its first visible page."""
import asyncio
import os
from concurrent.futures import Executor
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def _character_readiness():
    from character_recipe import make_recipe
    from readiness import check_readiness
    recipe = make_recipe(job_id="character_readiness", direction="an original person", mode="portrait",
                         trend_id="original", selections={}, sampler_seed=1, upsampler_seed=2, upsampler=True)
    return check_readiness(required_graph=recipe["graph_template"])


def register_optional_characters(app: FastAPI, executor: Executor, get_media_dir):
    disabled = os.getenv("OPENGENJUTSU_CHARACTER_STUDIO_ENABLED", "1").lower() in {"0", "false", "no", "off"}
    if disabled:
        return False
    from character_api import create_router
    from character_pipeline import run_character_pipeline
    app.include_router(create_router(get_media_dir, _character_readiness,
                       lambda job, opts: asyncio.get_running_loop().run_in_executor(executor, run_character_pipeline, job, opts)))
    template = Path(__file__).parent / "templates" / "character.html"

    @app.get("/characters", response_class=HTMLResponse)
    def characters_page():
        return template.read_text()

    return True
