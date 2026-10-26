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


def direction_facts_fixture() -> dict:
    return {
        "being": "woman", "role": "architect", "build": "a broad powerful build",
        "hair": "enormous sculptural silver hair", "face": "a square jaw and clear green eyes",
        "outfit": "a tailored navy wool suit", "attitude": "quietly amused with an upright stance",
        "primary_axis": "hair",
    }


def direction_wording_fixture(facts=None) -> str:
    facts = direction_facts_fixture() if facts is None else facts
    article = "an" if facts["role"][0].lower() in "aeiou" else "a"
    return (f"An original adult {facts['being']}, {article} {facts['role']}: {facts['build']}, "
            f"{facts['hair']}, {facts['face']}, wearing {facts['outfit']}, {facts['attitude']}.")


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


def v6_recipe_fixture() -> dict:
    """Captured v6 framing/input and graph digest, independent of the current assembler."""
    request = (
        "Full-length photograph of one life-sized original adult, both feet visible, natural camera "
        "perspective on a plain mid-grey seamless backdrop under soft neutral studio light; "
        "unretouched photographic skin texture, real hair and fabric, an original locksmith, "
        "no text, no letters, no logo, no watermark, no border, no frame, exactly one person, "
        "nothing cropped, clear eyes, coherent facial anatomy; natural adult head-to-body scale "
        "and limb lengths unless explicitly requested in the character idea; retain the requested "
        "distinctive hair, face, expression and build with lifelike skin pores and individual hair "
        "strands, empty hands, no hand-held or carried props"
    )
    graph = build_character_graph(request, 11, "3:4 (Portrait Standard)", True, "legacy_v6", upsampler_seed=29)
    graph_sha256 = "6e32a716edc932191d33c7209a96a2aa0830909947db73c6e008a65a1839f997"
    if digest_json(graph) != graph_sha256:
        raise AssertionError("The captured v6 graph no longer matches its frozen request")
    return {
        "schema_version": 6, "engine": ENGINE, "prompt_policy": "character-v6", "job_id": "legacy_v6",
        "raw_direction": "an original locksmith", "direction_origin": "generated", "trend_id": "original",
        "selections": {axis: "model_decides" for axis in
                       ("being", "build", "skin_tone", "hair", "face", "outfit", "role", "era", "attitude")},
        "mode": "portrait", "aspect_ratio": "3:4 (Portrait Standard)", "resolved_request": request,
        "sampler_seed": 11, "upsampler_seed": 29, "upsampler": True, "face_refine": False,
        "model_roles": copy.deepcopy(MODEL_ROLES), "vendor_workflow_sha256": VENDOR_WORKFLOW_SHA256,
        "system_prompt_sha256": SYSTEM_PROMPT_SHA256, "graph_template": graph, "graph_sha256": graph_sha256,
    }
