"""Comfy client construction and graph transport."""
import json
import uuid
from typing import Callable
from config import WORK, COMFY_BASE_URL

def make_client():
    """Build a Comfy SDK client. COMFY_BASE_URL selects the target."""
    from comfy_sdk import Comfy
    return Comfy()


def _run_graph(client, graph: dict, output_node: str, on_progress: Callable | None = None):
    """Submit a naked API-format graph and return the first output filename."""
    import urllib.request, urllib.error
    data = json.dumps({"workflow": graph}).encode()
    req = urllib.request.Request(
        f"{COMFY_BASE_URL}/api/v2/jobs",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"ComfyUI rejected workflow (HTTP {e.code}): {body[:500]}")
    job_id = resp.get("id")
    if not job_id:
        raise RuntimeError(f"No job id in response: {resp}")
    if on_progress:
        on_progress(f"job {job_id} submitted")
    # Poll for completion
    import time as _time
    deadline = _time.time() + 1800  # 30 min timeout
    while _time.time() < deadline:
        _time.sleep(5)
        try:
            with urllib.request.urlopen(f"{COMFY_BASE_URL}/api/v2/jobs/{job_id}", timeout=10) as r:
                st = json.load(r)
        except Exception:
            continue
        status = st.get("status")
        if on_progress:
            on_progress(f"job {job_id} {status}")
        if status == "succeeded":
            outputs = st.get("outputs", [])
            if not outputs:
                raise RuntimeError(f"no outputs on node {output_node}")
            # Find the output for our node
            for out in outputs:
                if out.get("node_id") == output_node:
                    url = out.get("url")
                    if url:
                        fname = out.get("name", f"output_{output_node}.png")
                        dest = WORK / "media" / fname
                        urllib.request.urlretrieve(url, dest)
                        return fname
            # Fallback: first output
            out = outputs[0]
            url = out.get("url")
            fname = out.get("name", f"output_{output_node}.png")
            dest = WORK / "media" / fname
            urllib.request.urlretrieve(url, dest)
            return fname
        elif status == "failed":
            raise RuntimeError(f"Job {job_id} failed: {st}")
    raise RuntimeError(f"Job {job_id} timed out after 30 min")


def _graph_to_workflow(client, graph: dict):
    """Fallback: write the graph to a temp file and load it as a workflow."""
    tmp = WORK / "media" / f"_graph_{uuid.uuid4().hex}.json"
    tmp.write_text(json.dumps(graph))
    return client.workflows.from_file(str(tmp))


