"""Frozen historical Character recipe fixtures; never use them to create new jobs."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from character_graphs import VENDOR_WORKFLOW_SHA256, build_character_graph
from character_recipe import (
    ENGINE,
    MODE_SPECS,
    MODEL_ROLES,
    SYSTEM_PROMPT_SHA256,
    digest_json,
)

_V1_PROMPT_POLICY = "character-v1"
_V1_SCHEMA_VERSION = 1
_V2_PROMPT_POLICY = "character-v2"
_V2_SCHEMA_VERSION = 2


_FIXTURE_PATH = Path(__file__).with_name("fixtures") / "character_recipe_v1_frozen.json"
_V2_FIXTURE_PATH = Path(__file__).with_name("fixtures") / "character_recipe_v2_frozen.json"


def v1_recipe_fixture() -> dict:
    """Rehydrate a captured v1 recipe with its old, non-reconstructed request."""
    frozen = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    graph = build_character_graph(frozen["resolved_request"], frozen["sampler_seed"],
                                  MODE_SPECS["portrait"]["aspect_ratio"], True, frozen["job_id"],
                                  upsampler_seed=frozen["upsampler_seed"])
    if digest_json(graph) != frozen["graph_sha256"]:
        raise AssertionError("The captured v1 graph no longer matches its frozen request")
    return {
        "schema_version": _V1_SCHEMA_VERSION,
        "engine": ENGINE,
        "prompt_policy": _V1_PROMPT_POLICY,
        "job_id": frozen["job_id"],
        "raw_direction": frozen["raw_direction"],
        "trend_id": "original",
        "selections": copy.deepcopy(frozen["selections"]),
        "mode": "portrait",
        "aspect_ratio": MODE_SPECS["portrait"]["aspect_ratio"],
        "resolved_request": frozen["resolved_request"],
        "sampler_seed": frozen["sampler_seed"],
        "upsampler_seed": frozen["upsampler_seed"],
        "upsampler": True,
        "model_roles": copy.deepcopy(MODEL_ROLES),
        "vendor_workflow_sha256": VENDOR_WORKFLOW_SHA256,
        "system_prompt_sha256": SYSTEM_PROMPT_SHA256,
        "graph_template": graph,
        "graph_sha256": frozen["graph_sha256"],
    }


def v2_recipe_fixture() -> dict:
    """Rehydrate a real v2 recipe exactly as it was frozen before v3 existed."""
    frozen = json.loads(_V2_FIXTURE_PATH.read_text(encoding="utf-8"))
    if (frozen.get("schema_version"), frozen.get("prompt_policy")) != (_V2_SCHEMA_VERSION, _V2_PROMPT_POLICY):
        raise AssertionError("The captured recipe is not v2 evidence")
    return copy.deepcopy(frozen)
