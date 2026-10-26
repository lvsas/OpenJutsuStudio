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
PROMPT_POLICY = "character-v7"
SCHEMA_VERSION = 7
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
HISTORICAL_MODE_SPECS = {
    "portrait": {"aspect_ratio": "3:4 (Portrait Standard)", "framing": PORTRAIT_FRAMING},
    "turnaround": {"aspect_ratio": "16:9 (Widescreen)", "framing": TURNAROUND_FRAMING},
}
MODE_SPECS = {
    "portrait": {
        "aspect_ratio": "3:4 (Portrait Standard)",
        "framing": "The waist-up portrait includes the entire hairstyle and the face clearly visible, "
                   "with space above the hair and a natural camera perspective.",
    },
    "full_body": {
        "aspect_ratio": "3:4 (Portrait Standard)",
        "framing": "The full-length portrait includes the entire figure, entire hairstyle and both feet visible, "
                   "with space around the silhouette and a natural camera perspective.",
    },
    "turnaround": {
        "aspect_ratio": "16:9 (Widescreen)",
        "framing": "The turnaround consists of four separate photographs of the same adult side by side at equal scale: "
                   "front view, three-quarter view, left profile, and back view. Each photograph includes "
                   "the entire figure, hairstyle and both feet, with identical clothing, hair and lighting.",
    },
}
_FACT_FIELDS = ("being", "role", "build", "hair", "face", "outfit", "attitude")
_PRIMARY_AXES = ("hair", "face", "build")
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
    if mode not in HISTORICAL_MODE_SPECS:
        raise ValueError("Unknown Character output mode")
    if "character sheet" in direction.lower():
        raise ValueError("Character requests must not use the phrase 'character sheet'")
    facts = [f"{axis.replace('_', ' ')}: {value}" for axis, value in selections.items()
             if value != MODEL_DECIDES]
    # Medium and framing first, then the character, then the explicit choices, then the negatives.
    if overrides and facts:
        facts.insert(0, "Explicit choices override conflicting details in the character idea")
    text = ", ".join([framing or HISTORICAL_MODE_SPECS[mode]["framing"], direction, *facts, negative_clause])
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


def _direction_facts(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != set(_FACT_FIELDS) | {"primary_axis"}:
        raise ValueError("Character direction facts snapshot must contain exactly the seven facts and primary_axis")
    facts = {field: _text(value[field], f"direction facts {field}", MAX_AXIS_TEXT, required=True)
             for field in _FACT_FIELDS}
    primary = value["primary_axis"]
    if not isinstance(primary, str) or primary not in _PRIMARY_AXES:
        raise ValueError("Character direction facts primary_axis must be hair, face or build")
    facts["primary_axis"] = primary
    return facts


def _article(role: str) -> str:
    return "an" if role[0].lower() in "aeiou" else "a"


def _facts_wording(facts: dict[str, str]) -> str:
    """Literal source contract shared with the suggested-proposal builder, before refinements."""
    return (f"An original adult {facts['being']}, {_article(facts['role'])} {facts['role']}: "
            f"{facts['build']}, {facts['hair']}, {facts['face']}, wearing {facts['outfit']}, {facts['attitude']}.")


def _noun_phrase(value: str) -> str:
    """Keep explicit articles from UI/free axis values without duplicating them."""
    if re.match(r"^(?:a|an|the)\s", value, re.IGNORECASE):
        return value
    return f"{_article(value)} {value}"


def _sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else text + "."


def _request_v7(mode: str, direction: str, selections: dict[str, str], direction_origin: str,
                facts: dict[str, str] | None) -> str:
    """Serialize one effective character, never append contradictory raw facts to refinements."""
    _direction_origin(direction_origin)
    selected = {axis: value for axis, value in selections.items() if value != MODEL_DECIDES}
    if facts is None:
        if selected:
            raise ValueError("Character refinements require a suggested proposal snapshot; "
                             "edit the idea directly or choose another suggested proposal")
        # Authored prose is opaque: no parsing, blind substitution or inferred structured identity.
        parts = ["Studio photograph of one original adult character.", _sentence(direction)]
    else:
        if direction != _facts_wording(facts):
            raise ValueError("Character direction must exactly match its source direction facts snapshot")
        effective = {**facts, **{axis: selected[axis] for axis in _FACT_FIELDS if axis in selected}}
        primary = facts["primary_axis"]
        others = [effective[axis] for axis in ("build", "hair", "face") if axis != primary]
        parts = [
            _sentence(f"Studio photograph of one original adult character: {_noun_phrase(effective['being'])}, "
                      f"{_noun_phrase(effective['role'])}, with {effective[primary]}"),
            _sentence(f"The character has {others[0]} and {others[1]}"),
        ]
        if "skin_tone" in selected:
            parts.append(_sentence(f"Their skin tone is {selected['skin_tone']}"))
        parts.append(_sentence(f"The character wears {effective['outfit']}"))
        if "era" in selected:
            parts.append(_sentence(f"The clothing and styling reflect {selected['era']}"))
        parts.append(_sentence(f"Their expression and posture are {effective['attitude']}"))
        if direction_origin == "generated":
            parts.append("Their hands are empty.")
    parts.extend([
        "Soft neutral studio light reveals lifelike skin texture, individual hair strands and real fabric "
        "against a plain mid-grey seamless backdrop.",
        MODE_SPECS[mode]["framing"],
    ])
    request = " ".join(parts)
    if "character sheet" in request.lower():
        raise ValueError("Character requests must not use the phrase 'character sheet'")
    return request


def make_recipe(*, job_id: str, direction: str, mode: str, trend_id: str, selections: dict[str, str] | None,
                sampler_seed: int, upsampler_seed: int, upsampler: bool,
                direction_origin: str = "generated", face_refine: bool = False,
                direction_facts: dict[str, str] | None = None) -> dict[str, Any]:
    """Resolve all Character choices before a graph is ever submitted."""
    raw_direction = direction
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
    facts = _direction_facts(direction_facts)
    request = _request_v7(mode, raw_direction if facts is not None else direction,
                          resolved, direction_origin, facts)
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
        "direction_facts": facts,
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
    if type(version) is not int:
        raise ValueError("Unsupported Character recipe contract")
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
    if type(version) is int and version == SCHEMA_VERSION and policy == PROMPT_POLICY:
        return AXES
    raise ValueError("Unsupported Character recipe contract")


def _validate_recipe_shape(recipe: Any) -> int:
    """Recognize frozen schemas without dispatching on Python's bool/int equality."""
    if not isinstance(recipe, dict):
        raise ValueError("Character recipe must be a JSON object")
    version = recipe.get("schema_version")
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7):
        raise ValueError("Unsupported Character recipe contract")
    required = {
        "schema_version", "engine", "prompt_policy", "job_id", "raw_direction", "trend_id", "selections",
        "mode", "aspect_ratio", "resolved_request", "sampler_seed", "upsampler_seed", "upsampler",
        "model_roles", "vendor_workflow_sha256", "system_prompt_sha256", "graph_template", "graph_sha256",
    }
    if recipe.get("schema_version") in (V3_SCHEMA_VERSION, V4_SCHEMA_VERSION, V5_SCHEMA_VERSION, 6, 7):
        required.add("direction_origin")
    if recipe.get("schema_version") in (6, 7):
        required.add("face_refine")
        if type(recipe.get("face_refine")) is not bool:
            raise ValueError("Character face_refine must be boolean")
    if recipe.get("schema_version") == 7:
        required.add("direction_facts")
    if set(recipe) != required or recipe.get("engine") != ENGINE:
        raise ValueError("Unsupported Character recipe contract")
    return version


def _validate_frozen_graph(recipe: dict[str, Any]) -> None:
    """Check recorded controls and provenance, never rebuild with today's graph/weights."""
    graph, roles = recipe["graph_template"], recipe["model_roles"]
    if not isinstance(graph, dict) or not graph or recipe["graph_sha256"] != digest_json(graph):
        raise ValueError("Character frozen graph digest changed")
    if any(not isinstance(node, dict) or not isinstance(node.get("class_type"), str)
           or not isinstance(node.get("inputs"), dict) for node in graph.values()):
        raise ValueError("Character frozen graph structure changed")
    refined = recipe.get("face_refine", False)
    role_keys = {"unet", "conditioning_encoder", "vae", "prompt_upsampler"}
    if refined:
        role_keys |= {"face_detector", "face_sam"}
    if (not isinstance(roles, dict) or set(roles) != role_keys
            or any(not isinstance(value, str) or not value.strip() for value in roles.values())):
        raise ValueError("Character frozen model-role map changed")
    controls = {
        ("18:17", "value"): recipe["resolved_request"],
        ("18:7", "seed"): recipe["sampler_seed"],
        ("18:11", "sampling_mode.seed"): recipe["upsampler_seed"],
        ("18:16", "switch"): recipe["upsampler"],
        ("19", "aspect_ratio"): recipe["aspect_ratio"],
        ("18:1", "unet_name"): roles["unet"],
        ("18:2", "clip_name"): roles["conditioning_encoder"],
        ("18:3", "vae_name"): roles["vae"],
        ("18:12", "clip_name"): roles["prompt_upsampler"],
    }
    refine_nodes = {"character_bbox", "character_sam", "character_detail", "character_refined"}
    if set(graph) & refine_nodes != (refine_nodes if refined else set()):
        raise ValueError("Character frozen face_refine graph changed")
    if refined:
        controls.update({("character_bbox", "model_name"): roles["face_detector"],
                         ("character_sam", "model_name"): roles["face_sam"],
                         ("character_detail", "seed"): recipe["sampler_seed"]})
    for (node_id, field), expected in controls.items():
        inputs = graph.get(node_id, {}).get("inputs", {})
        # JSON digests distinguish False/0, True/1 and integer/float graph literals.
        if field not in inputs or digest_json(inputs[field]) != digest_json(expected):
            raise ValueError("Character frozen graph controls changed")
    system = graph.get("18:14", {}).get("inputs", {}).get("value")
    if not isinstance(system, str) or digest_json(system) != recipe["system_prompt_sha256"]:
        raise ValueError("Character frozen system prompt changed")


def validate_frozen_recipe(recipe: Any) -> None:
    """Validate historical evidence in place, independent of current creation policy."""
    version = _validate_recipe_shape(recipe)
    for field in ("prompt_policy", "raw_direction", "resolved_request", "trend_id", "mode", "aspect_ratio"):
        if not isinstance(recipe[field], str) or not recipe[field].strip():
            raise ValueError("Character frozen recipe text changed")
    if not isinstance(recipe["job_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", recipe["job_id"]):
        raise ValueError("Character job identifier is invalid")
    for field in ("sampler_seed", "upsampler_seed"):
        _seed(recipe[field], field)
    if type(recipe["upsampler"]) is not bool:
        raise ValueError("Character prompt upsampler must be boolean")
    for field in ("graph_sha256", "vendor_workflow_sha256", "system_prompt_sha256"):
        if not isinstance(recipe[field], str) or not re.fullmatch(r"[0-9a-f]{64}", recipe[field]):
            raise ValueError("Character frozen recipe digest changed")
    if version >= 3:
        _direction_origin(recipe["direction_origin"])
    selections = _selections(recipe["selections"], V1_AXES if version == 1 else V5_AXES)
    if version == 7:
        facts = _direction_facts(recipe["direction_facts"])
        if facts != recipe["direction_facts"] or selections != recipe["selections"]:
            raise ValueError("Character frozen direction facts or selections changed")
        if facts is not None and recipe["raw_direction"] != _facts_wording(facts):
            raise ValueError("Character direction must exactly match its source direction facts snapshot")
        if facts is None and any(value != MODEL_DECIDES for value in selections.values()):
            raise ValueError("Character refinements require a suggested proposal snapshot")
    _validate_frozen_graph(recipe)


def validate_recipe(recipe: Any) -> dict[str, Any]:
    """Validate declared recipe versions without rewriting historical evidence."""
    _validate_recipe_shape(recipe)
    axes = _recipe_axes(recipe)
    direction = _text(recipe.get("raw_direction"), "direction", MAX_TEXT, required=True)
    job_id = recipe.get("job_id")
    if not isinstance(job_id, str):
        raise ValueError("Character job identifier is invalid")
    mode, trend_id = recipe.get("mode"), recipe.get("trend_id")
    mode_specs = MODE_SPECS if recipe["schema_version"] == 7 else HISTORICAL_MODE_SPECS
    if (not isinstance(mode, str) or not isinstance(trend_id, str)
            or mode not in mode_specs or trend_id not in TREND_LIBRARY):
        raise ValueError("Unsupported Character mode or trend")
    if recipe.get("aspect_ratio") != mode_specs[mode]["aspect_ratio"]:
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
    elif recipe["schema_version"] == 7:
        facts = _direction_facts(recipe["direction_facts"])
        if facts != recipe["direction_facts"]:
            raise ValueError("Character frozen direction facts snapshot changed")
        if selections != recipe["selections"]:
            raise ValueError("Character frozen selections changed")
        request = _request_v7(mode, recipe["raw_direction"], selections, recipe["direction_origin"], facts)
        if recipe.get("resolved_request") != request:
            raise ValueError("Character resolved request changed")
    else:
        direction_origin = _direction_origin(recipe.get("direction_origin"))
        assembler = {3: _request_v3, 4: _request_v4, 5: _request_v5, 6: _request_v5}[recipe["schema_version"]]
        request = assembler(mode, direction, selections, direction_origin)
        if recipe.get("resolved_request") != request:
            raise ValueError("Character resolved request changed")
    face_refine = recipe["schema_version"] in (6, 7) and recipe["face_refine"]
    if recipe.get("model_roles") != {**MODEL_ROLES, **(REFINE_MODEL_ROLES if face_refine else {})}:
        raise ValueError("Character model-role map changed")
    if (recipe.get("vendor_workflow_sha256") != VENDOR_WORKFLOW_SHA256
            or recipe.get("system_prompt_sha256") != SYSTEM_PROMPT_SHA256):
        raise ValueError("Character pinned workflow or system prompt changed")
    graph = build_character_graph(request, sampler_seed, mode_specs[mode]["aspect_ratio"],
                                  recipe["upsampler"], job_id, upsampler_seed=upsampler_seed)
    if face_refine:
        graph = append_face_refine(graph, seed=sampler_seed, job_id=job_id)
    supplied_graph = recipe.get("graph_template")
    expected_digest = digest_json(graph)
    if (not isinstance(supplied_graph, dict) or supplied_graph != graph
            or digest_json(supplied_graph) != recipe.get("graph_sha256")
            or recipe.get("graph_sha256") != expected_digest):
        raise ValueError("Character frozen graph changed")
    return copy.deepcopy(recipe)


def validate_current_recipe(recipe: Any) -> dict[str, Any]:
    """Validate an input that may be replayed under the current creation policy."""
    validated = validate_recipe(recipe)
    if validated["schema_version"] != SCHEMA_VERSION or validated["prompt_policy"] != PROMPT_POLICY:
        raise ValueError("This Character was frozen with an earlier policy; create a new Character instead of replaying it.")
    return validated
