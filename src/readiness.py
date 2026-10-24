"""Bounded, read-only checks before any local GPU work is accepted."""
import json
import logging
import os
import shutil
import socket
import threading
import time
from urllib.parse import urlsplit, quote
from urllib.request import Request, urlopen
from config import LOCAL_COMFY_PROXY_URL, comfy_base_url
from graphs import build_frame_edit, build_ripple

_LOG = logging.getLogger(__name__)
READINESS_HTTP_TIMEOUT_SECONDS = 4
CAPABILITY_TIMEOUT_SECONDS = 15
OBJECT_INFO_CACHE_TTL_SECONDS = 15
_OBJECT_INFO_CACHE = {}
_OBJECT_INFO_LOCK = threading.Lock()


def _json_get(url, headers=None, timeout=READINESS_HTTP_TIMEOUT_SECONDS):
    request_headers = {"Accept": "application/json", **(headers or {})}
    with urlopen(Request(url, headers=request_headers), timeout=timeout) as response:
        return json.load(response)


def _object_info(url, headers=None, *, cache=False):
    """Give capability inventory a realistic deadline and short local single-flight cache."""
    if not cache or headers:
        return _json_get(url, headers, timeout=CAPABILITY_TIMEOUT_SECONDS)
    with _OBJECT_INFO_LOCK:
        now = time.monotonic()
        for key, (expires, _) in list(_OBJECT_INFO_CACHE.items()):
            if expires <= now:
                _OBJECT_INFO_CACHE.pop(key, None)
        cached = _OBJECT_INFO_CACHE.get(url)
        if cached:
            return cached[1]
        info = _json_get(url, headers, timeout=CAPABILITY_TIMEOUT_SECONDS)
        _OBJECT_INFO_CACHE[url] = (now + OBJECT_INFO_CACHE_TTL_SECONDS, info)
        return info


def _is_timeout_error(exc):
    reason = getattr(exc, "reason", None)
    return isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(reason, (TimeoutError, socket.timeout))


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


def _inventory(info, required_graph=None):
    nodes, models = set(), set()
    graph = (list(required_graph.values()) if required_graph is not None else
             [*build_frame_edit("placeholder.png", "edit").values(),
              *build_ripple("placeholder.mp4", "placeholder.png").values()])
    for node in graph:
        name = node["class_type"]
        if name not in info:
            nodes.add(name)
            continue
        inputs = info[name].get("input", {})
        specs = {**inputs.get("required", {}), **inputs.get("optional", {})}
        for key, value in node["inputs"].items():
            if '.' in key:
                group, member = key.split('.', 1)
                dynamic = specs.get(group, [])
                if dynamic and dynamic[0] == 'COMFY_AUTOGROW_V3':
                    config = dynamic[1]['template']
                    suffix = member.removeprefix(config['prefix'])
                    if (not member.startswith(config['prefix']) or not suffix.isdecimal()
                            or int(suffix) >= config['max']):
                        raise ValueError('The reference count exceeds this installed target node capacity.')
            # A bundle-fed field is a node reference, not a literal filename.
            if not isinstance(value, str):
                continue
            if key in {"unet_name", "clip_name", "vae_name", "lora_name", "model_name"}:
                spec = specs.get(key, [])
                choices = (spec[0] if spec and isinstance(spec[0], list) else
                           spec[1].get("options", []) if len(spec) > 1 else [])
                if value not in choices:
                    models.add(value)
    return sorted(nodes), sorted(models)


def _probe_v2_jobs(base, api_key):
    """Health is public; a protected read checks credentials without GPU work."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    listing = _json_get(base + "/api/v2/jobs?limit=1", headers)
    if not isinstance(listing, dict) or not isinstance(listing.get("jobs"), list):
        raise ValueError("Expected Comfy API v2 job listing")


def _target_object_info(required_graph=None):
    """Inventory of the configured target, or raise when it cannot be inspected."""
    base = _valid_url(comfy_base_url())
    mode = _target_mode(base)
    if mode == 'self-hosted':
        health = _json_get(base + "/api/v2/health")
        if health.get("status") != "healthy" or not health.get("upstream"):
            raise ValueError("The configured self-hosted Comfy API Proxy is not healthy or has no upstream.")
        upstream = _valid_url(health['upstream'])
        if required_graph is not None:
            # Large installations can time out enumerating every unrelated
            # plugin. Query exactly the classes this compiled graph consumes.
            info = {}
            for name in sorted({node['class_type'] for node in required_graph.values()}):
                result = _object_info(upstream + '/object_info/' + quote(name, safe=''), cache=True)
                if not isinstance(result, dict):
                    raise ValueError('The required node inventory could not be read.')
                if name in result:
                    info[name] = result[name]
            return info
        return _object_info(upstream + '/object_info', cache=True)
    if mode == 'comfy-cloud':
        api_key = os.environ.get("COMFY_API_KEY", "").strip()
        if not api_key:
            raise ValueError("Set COMFY_API_KEY in the app process environment for this authenticated Comfy target.")
        return _object_info(base + "/api/object_info", {"X-API-Key": api_key})
    raise ValueError("This compute target does not expose a node/model inventory.")


def missing_dependencies(required_graph):
    """``(missing_nodes, missing_models)`` for one compiled graph.

    Refuse loudly when the target cannot be inspected: the alternative is
    submitting a graph the host may reject, which is the failure this gate
    exists to prevent. Nothing here writes, uploads or queues.
    """
    if not isinstance(required_graph, dict) or not required_graph:
        raise ValueError("A compiled graph is required for the target preflight")
    return _inventory(_target_object_info(required_graph), required_graph)


def check_readiness(required_graph=None):
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
                nodes, models = _inventory(_object_info(upstream + "/object_info", cache=True), required_graph)
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
                info = _object_info(base + "/api/object_info", {"X-API-Key": api_key})
                nodes, models = _inventory(info, required_graph)
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
    except Exception as exc:
        _LOG.warning('Configured Comfy readiness probe failed (%s)', type(exc).__name__)
        if _is_timeout_error(exc):
            issues.append("The Comfy readiness probe timed out. Retry; no generation job has been submitted.")
        else:
            issues.append("Cannot verify the configured Comfy target. Check its API v2 URL, authentication and service health; target details are not returned here.")
    report["ready"] = not issues
    return report
