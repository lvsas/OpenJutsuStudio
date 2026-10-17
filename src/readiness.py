"""Bounded, read-only checks before any local GPU work is accepted."""
import json
import os
import shutil
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from config import LOCAL_COMFY_PROXY_URL, comfy_base_url
from graphs import build_frame_edit, build_ripple


def _json_get(url, headers=None):
    request_headers = {"Accept": "application/json", **(headers or {})}
    with urlopen(Request(url, headers=request_headers), timeout=4) as response:
        return json.load(response)


def _valid_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Expected an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Credentials and query strings must not be embedded in the URL")
    return value.rstrip("/")


def _target_mode(base):
    parsed = urlsplit(base)
    host = (parsed.hostname or "").lower()
    if base.rstrip("/") == LOCAL_COMFY_PROXY_URL or host in {"127.0.0.1", "localhost", "::1"}:
        return "self-hosted"
    if host == "cloud.comfy.org":
        return "comfy-cloud"
    if host.endswith(".run.comfy.app"):
        return "comfy-api-deployment"
    return "remote-self-hosted"


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


def _probe_v2_jobs(base, api_key):
    """Health is public; a protected read checks credentials without GPU work."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    listing = _json_get(base + "/api/v2/jobs?limit=1", headers)
    if not isinstance(listing, dict) or not isinstance(listing.get("jobs"), list):
        raise ValueError("Expected Comfy API v2 job listing")


def check_readiness():
    """Check the configured Comfy target without leaking its URL or credentials."""
    issues, warnings = [], []
    report = {"ready": False, "mode": "unknown", "issues": issues,
              "warnings": warnings, "missing_nodes": [], "missing_models": []}
    for command in ("ffmpeg", "ffprobe"):
        if not shutil.which(command):
            issues.append(f"Install {command} and make it available on PATH.")
    try:
        base = _valid_url(comfy_base_url())
        mode = _target_mode(base)
        report["mode"] = mode
        if mode == "self-hosted":
            health = _json_get(base + "/api/v2/health")
            if health.get("status") != "healthy" or not health.get("upstream"):
                issues.append("The configured self-hosted Comfy API Proxy is not healthy or has no upstream.")
            else:
                upstream = _valid_url(health["upstream"])
                queue = _json_get(upstream + "/queue")
                if queue.get("queue_running") or queue.get("queue_pending"):
                    warnings.append("ComfyUI is busy. Your workflow can join its queue and will run after earlier jobs; waiting time is not inference time.")
                nodes, models = _inventory(_json_get(upstream + "/object_info"))
                report.update(missing_nodes=nodes, missing_models=models)
                if nodes:
                    issues.append("Install missing ComfyUI nodes: " + ", ".join(nodes))
                if models:
                    issues.append("Install the required models under their license terms: " + ", ".join(models))
        elif mode == "comfy-cloud":
            api_key = os.environ.get("COMFY_API_KEY", "").strip()
            if not api_key:
                issues.append("Set COMFY_API_KEY in the app process environment for this authenticated Comfy target; never put the key in the URL or repository.")
            else:
                info = _json_get(base + "/api/object_info", {"X-API-Key": api_key})
                nodes, models = _inventory(info)
                report.update(missing_nodes=nodes, missing_models=models)
                if nodes:
                    issues.append("The selected Comfy target is missing required nodes: " + ", ".join(nodes))
                if models:
                    issues.append("The selected Comfy target is missing required models: " + ", ".join(models))
        elif mode == "comfy-api-deployment":
            api_key = os.environ.get("COMFY_API_KEY", "").strip()
            if not api_key:
                issues.append("Set COMFY_API_KEY in the app process environment for this authenticated Comfy target.")
            else:
                _probe_v2_jobs(base, api_key)
                warnings.append("Deployment API v2 credentials are accepted. Upstream availability and node/model inventory are not fully verified; workflow submission remains the execution check.")
        else:
            api_key = os.environ.get("COMFY_API_KEY", "").strip()
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
            health = _json_get(base + "/api/v2/health", headers=headers)
            if health.get("status") != "healthy" or not health.get("upstream"):
                issues.append("The configured remote Comfy API v2 proxy is not healthy or has no upstream.")
            else:
                # A remote proxy may report a loopback/private upstream meaningful only on
                # its own host. Never follow that URL from this app process.
                _probe_v2_jobs(base, api_key)
                warnings.append("Remote proxy API access is verified. Upstream availability and node/model inventory are not fully verified; workflow submission remains the execution check.")
    except Exception:
        issues.append("Cannot verify the configured Comfy target. Check its API v2 URL, authentication and service health; target details are not returned here.")
    report["ready"] = not issues
    return report
