"""Immutable, path-free recipe for one FLUX 3 Viral Character artifact."""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import re
from typing import Any
from character_refine import append_face_refine, REFINE_MODEL_ROLES

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
V3_PROMPT_POLICY = "character-v3"
V3_SCHEMA_VERSION = 3
V3_AXES = V2_AXES
V4_PROMPT_POLICY = "character-v4"
V4_SCHEMA_VERSION = 4
V4_AXES = V3_AXES
V5_PROMPT_POLICY = "character-v5"
V5_SCHEMA_VERSION = 5
V5_AXES = V4_AXES
DIRECTION_ORIGINS = ("generated", "user_authored")
# Public aliases always describe recipes that can be newly created.
PROMPT_POLICY = "character-v6"
SCHEMA_VERSION = 6
AXES = V5_AXES
MAX_TEXT = 2_000
MAX_AXIS_TEXT = 300
MAX_SEED = 2**64 - 1
MODEL_DECIDES = "model_decides"
TREND_LIBRARY = {"original": {"label": "Original character", "source": "built_in"}}
# The mode owns medium, framing, views and environment; the direction owns only the character.
# Nothing here asks for a "character sheet": that noun makes the upsampler plan an illustration.
V2_NEGATIVE_CLAUSE = ("no text, no letters, no logo, no watermark, no border, no frame, "
                      "exactly one person, nothing cropped, clear eyes, plausible facial anatomy, "
                      "unexaggerated natural expression")
# Measured against the vendor TextGenerate upsampler: this wording prevents it from inventing a
# prop while preserving whole-body framing. It applies only to a generated proposal, never to a
# direction the user deliberately authored.
GENERATED_NO_PROP_CLAUSE = "no held, carried, worn, or visible props; no object in the hands or on the body"
V3_NEGATIVE_CLAUSE = f"{V2_NEGATIVE_CLAUSE}, {GENERATED_NO_PROP_CLAUSE}"
V4_NEGATIVE_CLAUSE = ("no text, no letters, no logo, no watermark, no border, no frame, "
                      "exactly one person, nothing cropped, clear eyes, coherent facial anatomy; "
                      "preserve the intentional exaggeration of proportions, hair and expression; "
                      "real skin and fabric detail, not a drawing, toy or plastic figurine")
V4_GENERATED_NO_PROP_CLAUSE = "empty hands, no hand-held or carried props"
V5_NEGATIVE_CLAUSE = (
    "no text, no letters, no logo, no watermark, no border, no frame, exactly one person, "
    "nothing cropped, clear eyes, coherent facial anatomy; natural adult head-to-body scale "
    "and limb lengths unless explicitly requested in the character idea; retain the requested "
    "distinctive hair, face, expression and build with lifelike skin pores and individual hair strands"
)
NEGATIVE_CLAUSE = V5_NEGATIVE_CLAUSE
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
V4_PORTRAIT_FRAMING = (
    "Studio photograph, full-body portrait, one original adult human character standing with both feet "
    "visible on a plain mid-grey seamless backdrop under soft even lighting; photographic skin, "
    "hair and fabric textures with the deliberately caricatured features described in the idea"
)
V5_PORTRAIT_FRAMING = (
    "Full-length photograph of one life-sized original adult, both feet visible, natural camera "
    "perspective on a plain mid-grey seamless backdrop under soft neutral studio light; "
    "unretouched photographic skin texture, real hair and fabric"
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


def _request_with_clause(mode: str, direction: str, selections: dict[str, str], negative_clause: str,
                         *, framing: str | None = None, overrides: bool = False) -> str:
    if mode not in MODE_SPECS:
        raise ValueError("Unknown Character output mode")
    if "character sheet" in direction.lower():
        raise ValueError("Character requests must not use the phrase 'character sheet'")
    facts = [f"{axis.replace('_', ' ')}: {value}" for axis, value in selections.items()
             if value != MODEL_DECIDES]
    # Medium and framing first, then the character, then the explicit choices, then the negatives.
    if overrides and facts:
        facts.insert(0, "Explicit choices override conflicting details in the character idea")
    text = ", ".join([framing or MODE_SPECS[mode]["framing"], direction, *facts, negative_clause])
    if "character sheet" in text.lower():
        raise ValueError("Character requests must not use the phrase 'character sheet'")
    return text


def _direction_origin(value: Any) -> str:
    if not isinstance(value, str) or value not in DIRECTION_ORIGINS:
        raise ValueError("Character direction origin is unsupported")
    return value


def _request_v2(mode: str, direction: str, selections: dict[str, str]) -> str:
    return _request_with_clause(mode, direction, selections, V2_NEGATIVE_CLAUSE)


def _request_v3(mode: str, direction: str, selections: dict[str, str], direction_origin: str) -> str:
    origin = _direction_origin(direction_origin)
    clause = V3_NEGATIVE_CLAUSE if origin == "generated" else V2_NEGATIVE_CLAUSE
    return _request_with_clause(mode, direction, selections, clause)


def _request_v4(mode: str, direction: str, selections: dict[str, str], direction_origin: str) -> str:
    origin = _direction_origin(direction_origin)
    clause = V4_NEGATIVE_CLAUSE
    if origin == "generated":
        clause += ", " + V4_GENERATED_NO_PROP_CLAUSE
    framing = V4_PORTRAIT_FRAMING if mode == "portrait" else None
    return _request_with_clause(mode, direction, selections, clause, framing=framing, overrides=True)


def _request_v5(mode: str, direction: str, selections: dict[str, str], direction_origin: str) -> str:
    clause = V5_NEGATIVE_CLAUSE
    if _direction_origin(direction_origin) == "generated":
        clause += ", " + V4_GENERATED_NO_PROP_CLAUSE
    framing = V5_PORTRAIT_FRAMING if mode == "portrait" else None
    return _request_with_clause(mode, direction, selections, clause, framing=framing, overrides=True)


def make_recipe(*, job_id: str, direction: str, mode: str, trend_id: str, selections: dict[str, str] | None,
                sampler_seed: int, upsampler_seed: int, upsampler: bool,
                direction_origin: str = "generated", face_refine: bool = False) -> dict[str, Any]:
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
    if type(face_refine) is not bool:
        raise ValueError("Character face_refine must be boolean")
    resolved = _selections(selections, AXES)
    direction_origin = _direction_origin(direction_origin)
    request = _request_v5(mode, direction, resolved, direction_origin)
    graph = build_character_graph(request, sampler_seed, MODE_SPECS[mode]["aspect_ratio"], upsampler, job_id,
                                  upsampler_seed=upsampler_seed)
    if face_refine:
        graph = append_face_refine(graph, seed=sampler_seed, job_id=job_id)
    recipe = {
        "schema_version": SCHEMA_VERSION,
        "engine": ENGINE,
        "prompt_policy": PROMPT_POLICY,
        "job_id": job_id,
        "raw_direction": direction,
        "direction_origin": direction_origin,
        "trend_id": trend_id,
        "selections": resolved,
        "mode": mode,
        "aspect_ratio": MODE_SPECS[mode]["aspect_ratio"],
        "resolved_request": request,
        "sampler_seed": sampler_seed,
        "upsampler_seed": upsampler_seed,
        "upsampler": upsampler,
        "face_refine": face_refine,
        "model_roles": {**MODEL_ROLES, **(REFINE_MODEL_ROLES if face_refine else {})},
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
    if version == V3_SCHEMA_VERSION and policy == V3_PROMPT_POLICY:
        return V3_AXES
    if version == V4_SCHEMA_VERSION and policy == V4_PROMPT_POLICY:
        return V4_AXES
    if version == V5_SCHEMA_VERSION and policy == V5_PROMPT_POLICY:
        return V5_AXES
    if type(version) is int and version == 6 and policy == "character-v6":
        return V5_AXES
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
    if recipe.get("schema_version") in (V3_SCHEMA_VERSION, V4_SCHEMA_VERSION, V5_SCHEMA_VERSION, 6):
        required.add("direction_origin")
    if recipe.get("schema_version") == 6:
        required.add("face_refine")
        if type(recipe.get("face_refine")) is not bool:
            raise ValueError("Character face_refine must be boolean")
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
    elif recipe["schema_version"] == V2_SCHEMA_VERSION:
        request = _request_v2(mode, direction, selections)
        if recipe.get("resolved_request") != request:
            raise ValueError("Character resolved request changed")
    else:
        direction_origin = _direction_origin(recipe.get("direction_origin"))
        assembler = {3: _request_v3, 4: _request_v4, 5: _request_v5, 6: _request_v5}[recipe["schema_version"]]
        request = assembler(mode, direction, selections, direction_origin)
        if recipe.get("resolved_request") != request:
            raise ValueError("Character resolved request changed")
    face_refine = recipe["schema_version"] == 6 and recipe["face_refine"]
    if recipe.get("model_roles") != {**MODEL_ROLES, **(REFINE_MODEL_ROLES if face_refine else {})}:
        raise ValueError("Character model-role map changed")
    if (recipe.get("vendor_workflow_sha256") != VENDOR_WORKFLOW_SHA256
            or recipe.get("system_prompt_sha256") != SYSTEM_PROMPT_SHA256):
        raise ValueError("Character pinned workflow or system prompt changed")
    graph = build_character_graph(request, sampler_seed, MODE_SPECS[mode]["aspect_ratio"],
                                  recipe["upsampler"], job_id, upsampler_seed=upsampler_seed)
    if face_refine:
        graph = append_face_refine(graph, seed=sampler_seed, job_id=job_id)
    if recipe.get("graph_template") != graph or recipe.get("graph_sha256") != digest_json(graph):
        raise ValueError("Character frozen graph changed")
    return copy.deepcopy(recipe)


def validate_current_recipe(recipe: Any) -> dict[str, Any]:
    """Validate an input that may be replayed under the current creation policy."""
    validated = validate_recipe(recipe)
    if validated["schema_version"] != SCHEMA_VERSION or validated["prompt_policy"] != PROMPT_POLICY:
        raise ValueError("This Character was frozen with an earlier policy; create a new Character instead of replaying it.")
    return validated
