"""Canonical FLUX 3 Klein workflow adapter for Character Studio.

The vendor owns the 19-node topology in ``workflows/flux3-klein-official-t2i.json``.
This module owns only the runtime controls OpenGenjutsu is allowed to patch. Rebuilding this
workflow by hand already produced a valid-but-wrong FLUX 2-shaped graph, so the structural contract
here is intentionally strict: drift must fail before a job reaches a GPU.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENDOR_WORKFLOW_PATH = ROOT / "workflows" / "flux3-klein-official-t2i.json"

# The vendor file omits this subdirectory. Its value is resolved from the live target's UNETLoader
# COMBO and is deliberately held here, rather than supplied by a browser request.
LOCAL_UNET = "flux/flux3-image-klein-base-int8-convrot.safetensors"
IMAGE_OUTPUT_NODE = "9"
TEXT_OUTPUT_NODE = "character_caption"
# Canonical JSON digest of the tracked 19-node upstream API export. Any vendor-file change is a
# deliberate migration, requiring a new validation and a reviewed constant update.
VENDOR_WORKFLOW_SHA256 = "69d685d1d9790312a09bf50e71c9b1ff37b4f001273524e8ed48dda61e238f1f"
MAX_REQUEST_CHARS = 2_000
MAX_SEED = 2**64 - 1
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")

# The vendor's live path. The layout branch remains in the graph verbatim even though it only feeds
# a preview in this template; removing it would make us own a different topology.
_REQUIRED_NODES = {
    "9": "SaveImage", "19": "ResolutionSelector", "25": "CreateBoundingBoxes",
    "26": "PreviewAny", "27": "Flux3LayoutPrompt", "18:1": "UNETLoader",
    "18:2": "CLIPLoader", "18:3": "VAELoader", "18:4": "CLIPTextEncode",
    "18:5": "CLIPTextEncode", "18:6": "EmptyFlux2LatentImage", "18:7": "KSampler",
    "18:8": "VAEDecode", "18:11": "TextGenerate", "18:12": "CLIPLoader",
    "18:13": "PreviewAny", "18:14": "PrimitiveStringMultiline",
    "18:16": "ComfySwitchNode", "18:17": "PrimitiveStringMultiline",
}
_EXPECTED_LINKS = {
    ("18:11", "prompt"): ["18:17", 0],
    ("18:11", "clip"): ["18:12", 0],
    ("18:16", "on_true"): ["18:11", 0],
    ("18:16", "on_false"): ["18:17", 0],
    ("18:13", "source"): ["18:16", 0],
    ("18:4", "text"): ["18:13", 0],
    ("18:4", "clip"): ["18:2", 0],
    ("18:7", "positive"): ["18:4", 0],
    ("18:7", "negative"): ["18:5", 0],
    ("18:7", "latent_image"): ["18:6", 0],
    ("18:8", "samples"): ["18:7", 0],
    ("9", "images"): ["18:8", 0],
    ("27", "element"): ["25", 2],
    ("26", "source"): ["27", 0],
}


_REQUIRED_RUNTIME_INPUTS = {
    "18:1": {"unet_name"}, "18:7": {"seed"}, "18:11": {"sampling_mode.seed"},
    "18:16": {"switch"}, "18:17": {"value"}, "19": {"aspect_ratio"},
    "9": {"filename_prefix"},
}


def _canonical_sha256(graph: dict[str, Any]) -> str:
    encoded = json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_vendor() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(VENDOR_WORKFLOW_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("The tracked FLUX 3 vendor workflow is unreadable") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("The tracked FLUX 3 vendor workflow is not an API graph")
    return raw


def validate_vendor_workflow(graph: dict[str, dict[str, Any]]) -> None:
    """Reject topology drift before runtime controls are patched."""
    if set(graph) != set(_REQUIRED_NODES) or len(graph) != 19:
        raise RuntimeError("FLUX 3 vendor workflow must contain its canonical 19 nodes")
    for node_id, node_type in _REQUIRED_NODES.items():
        node = graph.get(node_id, {})
        if node.get("class_type") != node_type:
            raise RuntimeError(f"FLUX 3 vendor workflow changed node {node_id}")
        if not isinstance(node.get("inputs"), dict):
            raise RuntimeError(f"FLUX 3 vendor workflow lost inputs for node {node_id}")
    for node_id, fields in _REQUIRED_RUNTIME_INPUTS.items():
        missing = fields - set(graph[node_id]["inputs"])
        if missing:
            raise RuntimeError(f"FLUX 3 vendor workflow lost runtime input(s) on {node_id}: {sorted(missing)}")
    for (node_id, field), expected in _EXPECTED_LINKS.items():
        if graph[node_id].get("inputs", {}).get(field) != expected:
            raise RuntimeError(f"FLUX 3 vendor workflow changed {node_id}.{field}")
    aspect = graph["19"].get("inputs", {}).get("aspect_ratio")
    if not isinstance(aspect, str) or not aspect:
        raise RuntimeError("FLUX 3 vendor workflow has no aspect-ratio selector")
    if _canonical_sha256(graph) != VENDOR_WORKFLOW_SHA256:
        raise RuntimeError("FLUX 3 vendor workflow content drifted from the pinned canonical export")


def load_vendor_graph() -> dict[str, dict[str, Any]]:
    """Read, validate and deep-copy the tracked source topology for one request."""
    graph = _read_vendor()
    validate_vendor_workflow(graph)
    return copy.deepcopy(graph)


def _vendor_aspect_ratios() -> tuple[str, ...]:
    graph = load_vendor_graph()
    # An API-format export keeps only ResolutionSelector's chosen literal. The complete menu came
    # from this target's live /object_info and remains an explicit product allow-list. Readiness
    # revalidates every selected literal against the chosen deployment before queueing.
    if not isinstance(graph["19"].get("inputs", {}).get("aspect_ratio"), str):
        raise RuntimeError("FLUX 3 vendor workflow has no selected aspect ratio")
    return (
        "1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)",
        "3:4 (Portrait Standard)", "4:3 (Standard)", "9:16 (Portrait Widescreen)",
        "16:9 (Widescreen)", "21:9 (Ultrawide)",
    )


ASPECT_RATIOS = _vendor_aspect_ratios()


def workflow_sha256(graph: dict[str, Any]) -> str:
    """Canonical digest for frozen graph provenance, independent of JSON formatting."""
    return _canonical_sha256(graph)


def _request(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Character direction must be non-empty text")
    if len(value) > MAX_REQUEST_CHARS:
        raise ValueError(f"Character direction must contain at most {MAX_REQUEST_CHARS} characters")
    return value


def _seed(value: int) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SEED:
        raise ValueError("Character seed must be an unsigned 64-bit integer")
    return value


def _job_id(value: str) -> str:
    if not isinstance(value, str) or not _JOB_ID.fullmatch(value):
        raise ValueError("Character job identifier is invalid")
    return value


def _prefix(job_id: str, artifact: str) -> str:
    return f"OpenGenjutsu/characters/{job_id}/{artifact}"


def build_character_graph(request: str, seed: int, aspect_ratio: str, upsampler: bool,
                          job_id: str) -> dict[str, dict[str, Any]]:
    """Clone the vendor graph and patch only the declared Character runtime controls."""
    request, seed, job_id = _request(request), _seed(seed), _job_id(job_id)
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError("Character aspect ratio is not supported by the vendor selector")
    if type(upsampler) is not bool:
        raise ValueError("Character prompt upsampler must be boolean")

    graph = load_vendor_graph()
    graph["18:17"]["inputs"]["value"] = request
    graph["18:1"]["inputs"]["unet_name"] = LOCAL_UNET
    graph["19"]["inputs"]["aspect_ratio"] = aspect_ratio
    graph["18:16"]["inputs"]["switch"] = upsampler
    graph["18:7"]["inputs"]["seed"] = seed
    graph["18:11"]["inputs"]["sampling_mode.seed"] = seed
    graph[IMAGE_OUTPUT_NODE]["inputs"]["filename_prefix"] = _prefix(job_id, "image")
    graph[TEXT_OUTPUT_NODE] = {
        "class_type": "SaveText",
        "inputs": {
            "text": ["18:13", 0],
            "filename_prefix": _prefix(job_id, "caption"),
            "format": "txt",
        },
        "_meta": {"title": "SAVE — Character resolved caption"},
    }
    return graph
