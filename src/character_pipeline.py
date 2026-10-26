"""Isolated FLUX 3 Character worker: frozen graph -> verified artifacts -> capsule."""
from __future__ import annotations

import copy
import shutil
import struct
import time
import zlib
from pathlib import Path
from typing import Any

import core
from character_capsule import freeze_capsule
from character_graphs import IMAGE_OUTPUT_NODE, TEXT_OUTPUT_NODE
from character_recipe import ENGINE, validate_recipe
from character_refine import REFINED_OUTPUT_NODE
from comfy_transport import _run_graph_artifacts, make_client


_ARTIFACT_REQUESTS = {
    "image": (IMAGE_OUTPUT_NODE, {".png"}),
    "caption": (TEXT_OUTPUT_NODE, {".txt"}),
}
_EXPECTED_RATIOS = {"portrait": 3 / 4, "turnaround": 16 / 9}


def _validate_png(path: Path, mode: str) -> tuple[int, int]:
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Character image is not a PNG")
    offset, width, height, expected_raw, idat = 8, None, None, None, []
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError("Character PNG is truncated")
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(raw):
            raise ValueError("Character PNG chunk is truncated")
        payload, declared_crc = raw[offset + 8:offset + 8 + length], raw[offset + 8 + length:end]
        if struct.unpack(">I", declared_crc)[0] != (zlib.crc32(kind + payload) & 0xffffffff):
            raise ValueError("Character PNG chunk CRC is invalid")
        if kind == b"IHDR":
            if width is not None or length != 13:
                raise ValueError("Character PNG has no valid IHDR")
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", payload)
            channels = {2: 3, 6: 4}.get(color_type)
            if (not width or not height or bit_depth not in {8, 16} or channels is None
                    or compression != 0 or filter_method != 0 or interlace != 0):
                raise ValueError("Character PNG metadata is invalid")
            expected_raw = height * (1 + width * channels * (bit_depth // 8))
            if expected_raw > 64 * 1024 * 1024:
                raise ValueError("Character PNG decoded payload is too large")
        elif kind == b"IDAT":
            if width is None:
                raise ValueError("Character PNG IDAT precedes IHDR")
            idat.append(payload)
        elif kind == b"IEND":
            if length != 0 or offset != len(raw) - 12 or width is None or not idat:
                raise ValueError("Character PNG IEND is invalid")
            try:
                decoded = zlib.decompress(b"".join(idat))
            except zlib.error as exc:
                raise ValueError("Character PNG IDAT cannot be decoded") from exc
            if len(decoded) != expected_raw:
                raise ValueError("Character PNG decoded payload is invalid")
            target = _EXPECTED_RATIOS[mode]
            if abs(width / height - target) > 0.02:
                raise ValueError("Character PNG aspect ratio differs from the frozen mode")
            if width is None or height is None:
                raise ValueError("Character PNG dimensions are missing")
            return width, height
        offset = end
    raise ValueError("Character PNG has no IEND")


def _validate_caption(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Character caption is not UTF-8") from exc
    if not text.strip():
        raise ValueError("Character caption is empty")
    return text


def _progress(job, state: str) -> None:
    job.step = f"character_{state}"
    job.progress = {"submitting": 0.15, "downloaded": 0.85}.get(state, job.progress)
    job.save()


def run_character_pipeline(job, opts: dict[str, Any]) -> None:
    """Run one pre-frozen Character recipe in the app's normal single-worker executor."""
    client = None
    folder: Path | None = None
    published = False
    job.status, job.started, job.finished = "running", time.time(), None
    job.step, job.progress, job.result, job.error = "character_prepare", 0.02, None, None
    job.meta.pop("character_capsule", None)
    job.meta.pop("character_caption", None)
    job.meta.pop("character_base_image", None)
    job.save()
    try:
        if job.engine != ENGINE:
            raise ValueError("Character runner accepts only FLUX 3 Character jobs")
        if not isinstance(opts, dict):
            raise ValueError("Character worker options must be an object")
        queued_recipe = validate_recipe(copy.deepcopy(job.meta.get("character_recipe")))
        provided_recipe = validate_recipe(copy.deepcopy(opts["recipe"]))
        if queued_recipe != provided_recipe:
            raise ValueError("Character worker recipe differs from the queued frozen recipe")
        recipe = queued_recipe
        if recipe["job_id"] != job.id:
            raise ValueError("Character worker recipe does not belong to this job")
        media_dir = Path(opts.get("media_dir", core.WORK / "media")).resolve()
        media_dir.mkdir(parents=True, exist_ok=True)
        job.path  # Validate the identifier before creating any output namespace.
        folder = media_dir / f"character-{job.id}"
        job.meta["character_recipe"] = copy.deepcopy(recipe)
        job.save()
        client = make_client()
        requests = copy.deepcopy(_ARTIFACT_REQUESTS)
        if recipe.get("face_refine") is True:
            requests.update(image=(REFINED_OUTPUT_NODE, {".png"}), base_image=(IMAGE_OUTPUT_NODE, {".png"}))
        artifacts = _run_graph_artifacts(
            client, recipe["graph_template"], requests, folder,
            on_progress=lambda state: _progress(job, state),
        )
        published = True
        image, caption = artifacts["image"], artifacts["caption"]
        width, height = _validate_png(image, recipe["mode"])
        if recipe.get("face_refine") is True:
            base = artifacts["base_image"]
            if base.resolve() == image.resolve():
                raise ValueError("Character base image must be a separate artifact")
            if _validate_png(base, recipe["mode"]) != (width, height):
                raise ValueError("Character base image dimensions differ from the refined image")
            job.meta["character_base_image"] = str(base.resolve())
        _validate_caption(caption)
        job.result = str(image.resolve())
        job.meta.update(character_caption=str(caption.resolve()), character_dimensions={"width": width, "height": height})
        freeze_capsule(job, recipe, image, caption, media_dir)
        job.status, job.step, job.progress = "done", "done", 1.0
    except Exception as exc:
        job.status, job.step, job.progress = "error", "character_error", 1.0
        job.error, job.result = f"{type(exc).__name__}: {exc}", None
        job.meta.pop("character_caption", None)
        job.meta.pop("character_capsule", None)
        job.meta.pop("character_dimensions", None)
        job.meta.pop("character_base_image", None)
        if published and folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        job.finished = time.time()
        job.save()
