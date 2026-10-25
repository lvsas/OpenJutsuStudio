"""Inspectable, declared local runtime contract for contest evidence."""
from __future__ import annotations

from typing import Any

import config
from graphs import build_frame_edit, build_ripple


MODEL_FILES = {
    "flux_unet": config.F_UNET_KLEIN,
    "flux_clip": config.F_CLIP_KLEIN,
    "flux_vae": config.F_VAE_KLEIN,
    "ltx_unet": config.F_UNET_LTX,
    "ltx_clip": config.F_CLIP_LTX,
    "video_vae": config.F_VAE_VID,
    "audio_vae": config.F_VAE_AUD,
    "ripple_lora": config.F_LORA_RIPPLE,
}


def workflow_node_types() -> list[str]:
    """List all declared node types without submitting a workflow."""
    graph = [
        *build_frame_edit("placeholder.png", "edit").values(),
        *build_ripple("placeholder.mp4", "placeholder.png").values(),
    ]
    return sorted({node["class_type"] for node in graph})


def declared_runtime_inventory() -> dict[str, Any]:
    """Return declarations, not a claim that every model file is present or eligible."""
    return {
        "schema_version": 2,
        "engine": "ltx25-ripple",
        "inference": {
            "mode": "configurable-api-v2",
            "transport": "official comfy-sdk to Comfy API v2",
            "default_proxy": config.LOCAL_COMFY_PROXY_URL,
            "target_selection": "Settings first, otherwise OPENGENJUTSU_COMFY_BASE_URL or the local default; ambient COMFY_BASE_URL is ignored",
            "supported_target_modes": ["self-hosted", "remote-self-hosted", "comfy-cloud", "comfy-api-deployment"],
            "hosted_render_verified": False,
        },
        "declared_model_files": MODEL_FILES,
        "declared_workflow_nodes": workflow_node_types(),
        "verification": {
            "readiness_endpoint": "/api/readiness",
            "what_it_checks": "self-hosted proxy health, upstream queue, declared node availability and declared model filenames",
            "what_it_does_not_prove": "model licensing, model-file hashes, organizer eligibility, or output quality",
        },
    }
