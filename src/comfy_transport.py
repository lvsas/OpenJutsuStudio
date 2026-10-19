"""One official SDK transport for local proxy and authenticated deployments."""
import ctypes
import errno
import os
import re
import shutil
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


_ARTIFACT_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_NODE_ID = re.compile(r"(?:\d+|\d+:\d+|[A-Za-z_][A-Za-z0-9_]*)\Z")
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


def _publish_directory(staging: Path, destination: Path) -> None:
    """Atomically expose a complete artifact directory without replacing another publisher."""
    if os.name != "posix":
        raise RuntimeError("Atomic no-clobber artifact publication requires a POSIX target")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RuntimeError("This POSIX target lacks renameat2 no-clobber publication")
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    result = renameat2(_AT_FDCWD, os.fsencode(staging), _AT_FDCWD, os.fsencode(destination),
                       _RENAME_NOREPLACE)
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise FileExistsError(f"SDK artifact destination already exists: {destination}")
    raise OSError(error, os.strerror(error), destination)


def _run_graph_artifacts(client, graph: dict, requested: dict[str, tuple[str, set[str]]],
                         folder: Path, on_progress: Callable | None = None) -> dict[str, Path]:
    """Run one graph and atomically publish exact SDK artifacts in a new directory.

    ``requested`` maps a server-owned role to exactly one output node and its allowed extensions.
    The destination directory must not exist. Downloads remain in a private sibling directory until
    every requested output is present, non-empty and extension-checked; Linux `renameat2` then makes
    the complete directory visible without replacing a concurrent publisher.
    """
    if not requested:
        raise ValueError("At least one requested SDK artifact is required")
    root = Path(folder)
    if os.path.lexists(root):
        raise FileExistsError(f"SDK artifact destination already exists: {root}")
    normalized: dict[str, tuple[str, set[str]]] = {}
    for role, specification in requested.items():
        if not isinstance(role, str) or not _ARTIFACT_ROLE.fullmatch(role):
            raise ValueError("SDK artifact role is invalid")
        if not isinstance(specification, tuple) or len(specification) != 2:
            raise ValueError("SDK artifact specification must be (node_id, extensions)")
        node_id, extensions = specification
        if not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id):
            raise ValueError("SDK artifact node identifier is invalid")
        normalized_extensions = {str(extension).lower() for extension in extensions}
        if not normalized_extensions or any(not extension.startswith(".") for extension in normalized_extensions):
            raise ValueError("SDK artifact extensions must be non-empty dotted suffixes")
        normalized[role] = node_id, normalized_extensions

    root.parent.mkdir(parents=True, exist_ok=True)
    staging = root.parent / f".{root.name}.{uuid.uuid4().hex}.part"
    staging.mkdir(mode=0o700)
    published = False
    try:
        workflow = client.workflows.from_json(graph)
        if on_progress:
            on_progress("submitting")
        job = client.run(workflow, timeout=1800)
        staged: dict[str, Path] = {}
        for role, (node_id, extensions) in normalized.items():
            outputs = list(job.get_outputs(node_id) or [])
            if not outputs:
                raise RuntimeError(f"Missing output for requested {role} node {node_id}")
            if len(outputs) != 1:
                raise RuntimeError(f"Requested {role} node {node_id} returned {len(outputs)} artifacts")
            output = outputs[0]
            suffix = Path(str(output.name)).suffix.lower()
            if suffix not in extensions:
                raise RuntimeError(f"Requested {role} node {node_id} returned unsupported extension {suffix!r}")
            destination = staging / f"{role}{suffix}"
            partial = destination.with_suffix(destination.suffix + ".part")
            try:
                output.to_file(partial)
                if not partial.is_file() or not partial.stat().st_size:
                    raise RuntimeError(f"Downloaded {role} artifact was empty")
                partial.replace(destination)
            finally:
                partial.unlink(missing_ok=True)
            staged[role] = destination
        artifacts = {role: root / path.name for role, path in staged.items()}
        if on_progress:
            on_progress("downloaded")
        _publish_directory(staging, root)
        published = True
        return artifacts
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def _graph_to_workflow(client, graph: dict):
    """Construct a workflow in memory; do not create untracked temporary graphs."""
    return client.workflows.from_json(graph)
