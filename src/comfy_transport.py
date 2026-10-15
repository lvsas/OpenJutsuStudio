"""One official SDK transport for local proxy and authenticated deployments."""
import uuid
from pathlib import Path
from typing import Callable
from config import WORK, comfy_base_url


def make_client():
    """Use the same documented SDK base URL for assets, jobs and downloads."""
    from comfy_sdk import Comfy
    comfy_base_url()
    return Comfy()


def _run_graph(client, graph: dict, output_node: str, on_progress: Callable | None = None):
    """Run through the SDK; require the requested output, never another node."""
    workflow = client.workflows.from_json(graph)
    if on_progress:
        on_progress("submitting")
    job = client.run(workflow, timeout=1800)
    outputs = job.get_outputs(output_node)
    if not outputs:
        raise RuntimeError(f"Missing output for node {output_node}")
    output = outputs[0]
    filename = f"{uuid.uuid4().hex}_{Path(output.name).name}"
    dest = WORK / "media" / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    try:
        output.to_file(partial)
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
    if on_progress:
        on_progress("downloaded")
    return filename


def _graph_to_workflow(client, graph: dict):
    """Construct a workflow in memory; do not create untracked temporary graphs."""
    return client.workflows.from_json(graph)
