"""Immutable, path-free recipe for one FLUX 3 Viral Character artifact."""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import re
from typing import Any

from character_graphs import (
    ASPECT_RATIOS,
    LOCAL_UNET,
    VENDOR_WORKFLOW_SHA256,
    build_character_graph,
    load_vendor_graph,
)

ENGINE = "flux3-klein-character"
V1_PROMPT_POLICY = "character-v1"
V1_SCHEMA_VERSION = 1
V1_AXES = ("being", "build", "skin_tone", "hair", "face", "outfit", "role", "era", "accessory", "absurdity")
V2_PROMPT_POLICY = "character-v2"
V2_SCHEMA_VERSION = 2
V2_AXES = ("being", "build", "skin_tone", "hair", "face", "outfit", "role", "era", "attitude")
# Public aliases always describe recipes that can be newly created.
PROMPT_POLICY = V2_PROMPT_POLICY
SCHEMA_VERSION = V2_SCHEMA_VERSION
AXES = V2_AXES
MAX_TEXT = 2_000
MAX_AXIS_TEXT = 300
MAX_SEED = 2**64 - 1
MODEL_DECIDES = "model_decides"
TREND_LIBRARY = {"original": {"label": "Original character", "source": "built_in"}}
# The mode owns medium, framing, views and environment; the direction owns only the character.
# Nothing here asks for a "character sheet": that noun makes the upsampler plan an illustration.
NEGATIVE_CLAUSE = ("no text, no letters, no logo, no watermark, no border, no frame, "
                   "exactly one person, nothing cropped")
PORTRAIT_FRAMING = (
    "Studio photograph, three-quarter body, one person standing on a plain mid-grey seamless "
    "backdrop under soft even high-key lighting, sharp focus on the face, whole character in frame"
)
TURNAROUND_FRAMING = (
    "Studio photographic quadriptych: four separate photographs of the same one person side by side "
    "at equal scale on one plain mid-grey seamless backdrop, under soft even high-key lighting, "
    "showing four different viewing angles in this order — front view, three-quarter view, left "
    "profile, and back view — with identical clothing, hair and lighting in all four panels"
)
MODE_SPECS = {
    "portrait": {"aspect_ratio": "3:4 (Portrait Standard)", "framing": PORTRAIT_FRAMING},
    "turnaround": {"aspect_ratio": "16:9 (Widescreen)", "framing": TURNAROUND_FRAMING},
}
_PRIVATE_ADDRESS = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")


def digest_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _unsafe(value: str) -> bool:
    if "/" in value or "\\" in value or "://" in value or ".." in value:
        return True
    # A Windows drive path is a single letter, a colon and then a separator (`C:\`, `C:/`).
    # Matching a bare `[A-Za-z]:` rejected ordinary prose such as "An original character: ...".
    if re.search(r"[A-Za-z]:[\\/]", value):
        return True
    if "localhost" in value.lower():
        return True
    if "::1" in value:
        return True
    for candidate in _PRIVATE_ADDRESS.findall(value):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_private or address.is_loopback:
            return True
    return False


def _text(value: Any, name: str, limit: int, *, required: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Character {name} must be text")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"Character {name} must be non-empty")
    if len(normalized) > limit:
        raise ValueError(f"Character {name} must contain at most {limit} characters")
    if _unsafe(normalized):
        raise ValueError(f"Character {name} must not contain a path or private endpoint")
    return normalized


def _seed(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SEED:
        raise ValueError(f"Character {name} must be an unsigned 64-bit integer")
    return value


def _selections(value: Any, axes: tuple[str, ...]) -> dict[str, str]:
    if value is None:
        value = {}
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Character selections must be a JSON object")
    unknown = set(value) - set(axes)
    if unknown:
        raise ValueError(f"Unknown Character selection axis: {sorted(unknown)}")
    resolved = {}
    for axis in axes:
        raw = value.get(axis, "")
        selected = _text(raw, f"{axis} selection", MAX_AXIS_TEXT, required=False)
        resolved[axis] = selected or MODEL_DECIDES
    return resolved


def _model_roles() -> dict[str, str]:
    graph = load_vendor_graph()
    roles = {
        "unet": LOCAL_UNET,
        "conditioning_encoder": graph["18:2"]["inputs"]["clip_name"],
        "vae": graph["18:3"]["inputs"]["vae_name"],
        "prompt_upsampler": graph["18:12"]["inputs"]["clip_name"],
    }
    if any(not isinstance(value, str) or not value for value in roles.values()):
        raise RuntimeError("Pinned FLUX 3 workflow has an incomplete model-role map")
    return roles


MODEL_ROLES = _model_roles()
SYSTEM_PROMPT_SHA256 = digest_json(load_vendor_graph()["18:14"]["inputs"]["value"])


def _request(mode: str, direction: str, selections: dict[str, str]) -> str:
    if mode not in MODE_SPECS:
        raise ValueError("Unknown Character output mode")
    if "character sheet" in direction.lower():
        raise ValueError("Character requests must not use the phrase 'character sheet'")
    facts = [f"{axis.replace('_', ' ')}: {value}" for axis, value in selections.items()
             if value != MODEL_DECIDES]
    # Medium and framing first, then the character, then the explicit choices, then the negatives.
    text = ", ".join([MODE_SPECS[mode]["framing"], direction, *facts, NEGATIVE_CLAUSE])
    if "character sheet" in text.lower():
        raise ValueError("Character requests must not use the phrase 'character sheet'")
    return text


def make_recipe(*, job_id: str, direction: str, mode: str, trend_id: str, selections: dict[str, str] | None,
                sampler_seed: int, upsampler_seed: int, upsampler: bool) -> dict[str, Any]:
    """Resolve all Character choices before a graph is ever submitted."""
    direction = _text(direction, "direction", MAX_TEXT, required=True)
    if not isinstance(mode, str) or mode not in MODE_SPECS:
        raise ValueError("Unknown Character output mode")
    if mode and MODE_SPECS[mode]["aspect_ratio"] not in ASPECT_RATIOS:
        raise RuntimeError("Character mode is not supported by the pinned FLUX 3 ratio allow-list")
    if not isinstance(trend_id, str) or trend_id not in TREND_LIBRARY:
        raise ValueError("Unknown Character trend id")
    sampler_seed, upsampler_seed = _seed(sampler_seed, "sampler seed"), _seed(upsampler_seed, "upsampler seed")
    if type(upsampler) is not bool:
        raise ValueError("Character prompt upsampler must be boolean")
    resolved = _selections(selections, V2_AXES)
    request = _request(mode, direction, resolved)
    graph = build_character_graph(request, sampler_seed, MODE_SPECS[mode]["aspect_ratio"], upsampler, job_id,
                                  upsampler_seed=upsampler_seed)
    recipe = {
        "schema_version": SCHEMA_VERSION,
        "engine": ENGINE,
        "prompt_policy": PROMPT_POLICY,
        "job_id": job_id,
        "raw_direction": direction,
        "trend_id": trend_id,
        "selections": resolved,
        "mode": mode,
        "aspect_ratio": MODE_SPECS[mode]["aspect_ratio"],
        "resolved_request": request,
        "sampler_seed": sampler_seed,
        "upsampler_seed": upsampler_seed,
        "upsampler": upsampler,
        "model_roles": copy.deepcopy(MODEL_ROLES),
        "vendor_workflow_sha256": VENDOR_WORKFLOW_SHA256,
        "system_prompt_sha256": SYSTEM_PROMPT_SHA256,
        "graph_template": graph,
        "graph_sha256": digest_json(graph),
    }
    return validate_recipe(recipe)


def _recipe_axes(recipe: dict[str, Any]) -> tuple[str, ...]:
    version, policy = recipe.get("schema_version"), recipe.get("prompt_policy")
    if version == V1_SCHEMA_VERSION and policy == V1_PROMPT_POLICY:
        return V1_AXES
    if version == V2_SCHEMA_VERSION and policy == V2_PROMPT_POLICY:
        return V2_AXES
    raise ValueError("Unsupported Character recipe contract")


def validate_recipe(recipe: Any) -> dict[str, Any]:
    """Validate declared recipe versions without rewriting historical evidence."""
    if not isinstance(recipe, dict):
        raise ValueError("Character recipe must be a JSON object")
    required = {
        "schema_version", "engine", "prompt_policy", "job_id", "raw_direction", "trend_id", "selections",
        "mode", "aspect_ratio", "resolved_request", "sampler_seed", "upsampler_seed", "upsampler",
        "model_roles", "vendor_workflow_sha256", "system_prompt_sha256", "graph_template", "graph_sha256",
    }
    if set(recipe) != required or recipe.get("engine") != ENGINE:
        raise ValueError("Unsupported Character recipe contract")
    axes = _recipe_axes(recipe)
    direction = _text(recipe.get("raw_direction"), "direction", MAX_TEXT, required=True)
    job_id = recipe.get("job_id")
    if not isinstance(job_id, str):
        raise ValueError("Character job identifier is invalid")
    mode, trend_id = recipe.get("mode"), recipe.get("trend_id")
    if (not isinstance(mode, str) or not isinstance(trend_id, str)
            or mode not in MODE_SPECS or trend_id not in TREND_LIBRARY):
        raise ValueError("Unsupported Character mode or trend")
    if recipe.get("aspect_ratio") != MODE_SPECS[mode]["aspect_ratio"]:
        raise ValueError("Character aspect ratio does not match mode")
    sampler_seed = _seed(recipe.get("sampler_seed"), "sampler seed")
    upsampler_seed = _seed(recipe.get("upsampler_seed"), "upsampler seed")
    if type(recipe.get("upsampler")) is not bool:
        raise ValueError("Character prompt upsampler contract changed")
    selections = _selections(recipe.get("selections"), axes)
    if recipe["schema_version"] == V1_SCHEMA_VERSION:
        # v1 evidence predates the current framing/negative-clause contract. Its saved request is
        # the only truthful record of what reached the graph; do not reconstruct it with v2 wording.
        request = _text(recipe.get("resolved_request"), "resolved request", MAX_TEXT, required=True)
    else:
        request = _request(mode, direction, selections)
        if recipe.get("resolved_request") != request:
            raise ValueError("Character resolved request changed")
    if recipe.get("model_roles") != MODEL_ROLES:
        raise ValueError("Character model-role map changed")
    if (recipe.get("vendor_workflow_sha256") != VENDOR_WORKFLOW_SHA256
            or recipe.get("system_prompt_sha256") != SYSTEM_PROMPT_SHA256):
        raise ValueError("Character pinned workflow or system prompt changed")
    graph = build_character_graph(request, sampler_seed, MODE_SPECS[mode]["aspect_ratio"],
                                  recipe["upsampler"], job_id, upsampler_seed=upsampler_seed)
    if recipe.get("graph_template") != graph or recipe.get("graph_sha256") != digest_json(graph):
        raise ValueError("Character frozen graph changed")
    return copy.deepcopy(recipe)


def validate_current_recipe(recipe: Any) -> dict[str, Any]:
    """Validate an input that may be replayed under the current creation policy."""
    validated = validate_recipe(recipe)
    if validated["schema_version"] != SCHEMA_VERSION or validated["prompt_policy"] != PROMPT_POLICY:
        raise ValueError("This Character was frozen with an earlier policy; create a new Character instead of replaying it.")
    return validated
