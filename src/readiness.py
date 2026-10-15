"""Bounded, read-only checks before any local GPU work is accepted."""
import json
import shutil
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from config import comfy_base_url
from graphs import build_frame_edit, build_ripple


def _json_get(url):
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=4) as response:
        return json.load(response)


def _valid_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Expected an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Credentials and query strings must not be embedded in the URL")
    return value.rstrip("/")


def _inventory(info):
    nodes, models = set(), set()
    graph = [*build_frame_edit("placeholder.png", "edit").values(),
             *build_ripple("placeholder.mp4", "placeholder.png").values()]
    for node in graph:
        name = node["class_type"]
        if name not in info:
            nodes.add(name)
            continue
        inputs = info[name].get("input", {})
        specs = {**inputs.get("required", {}), **inputs.get("optional", {})}
        for key, value in node["inputs"].items():
            if key in {"unet_name", "clip_name", "vae_name", "lora_name"}:
                spec = specs.get(key, [])
                if not spec or value not in spec[0]:
                    models.add(value)
    return sorted(nodes), sorted(models)


def check_readiness():
    """Local proxy readiness, not a claim of Cloud support or GPU availability."""
    issues = []
    report = {"ready": False, "mode": "self-hosted", "issues": issues,
              "missing_nodes": [], "missing_models": []}
    for command in ("ffmpeg", "ffprobe"):
        if not shutil.which(command):
            issues.append(f"Install {command} and make it available on PATH.")
    try:
        base = _valid_url(comfy_base_url())
        health = _json_get(base + "/api/v2/health")
        if health.get("status") != "healthy" or not health.get("upstream"):
            issues.append("This gate requires a self-hosted Comfy API Proxy. Cloud is not validated.")
        else:
            upstream = _valid_url(health["upstream"])
            nodes, models = _inventory(_json_get(upstream + "/object_info"))
            report.update(missing_nodes=nodes, missing_models=models)
            if nodes:
                issues.append("Install missing ComfyUI nodes: " + ", ".join(nodes))
            if models:
                issues.append("Install the required models under their license terms: " + ", ".join(models))
    except Exception:
        issues.append("Cannot verify ComfyUI. Check COMFY_BASE_URL, start Comfy API Proxy, and check its upstream ComfyUI connection.")
    report["ready"] = not issues
    return report
