"""Integrity-preserving Character Capsule and replay boundary."""
from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any

from character_recipe import ENGINE, digest_json, validate_current_recipe, validate_recipe, validate_frozen_recipe


_ALLOWED_ARTIFACTS = {".png", ".txt"}
CAPSULE_FORMAT = "opengenjutsu-character-capsule"
# Which recipe schemas each capsule envelope may carry. build_capsule puts every recipe
# that is not 6 or 7 into envelope 2, so envelope 2 must accept the newest recipe too.
ENVELOPE_RECIPES = {1: (1, 2, 3, 4, 5), 2: (1, 2, 3, 4, 5, 8), 6: (6,), 7: (7,)}


def allowed_recipe_versions(envelope: int) -> tuple[int, ...]:
    return ENVELOPE_RECIPES[envelope]
CAPSULE_SCHEMA_VERSION = 7
LEGACY_CAPSULE_SCHEMA_VERSIONS = {1}
REPLAY_CONTRACT = "Verified image/caption bytes and frozen recipe; pixel-identical output is not guaranteed."
_JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def contained(path: str | Path, media_dir: str | Path) -> Path:
    root = Path(media_dir).resolve()
    candidate = Path(path)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if (not resolved.is_relative_to(root) or resolved == root or not resolved.is_file()
            or resolved.suffix.lower() not in _ALLOWED_ARTIFACTS):
        raise ValueError("Character artifact is missing or outside the media directory")
    return resolved


def digest_file(path: str | Path) -> str:
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _asset(path: str | Path, media_dir: str | Path) -> dict[str, Any]:
    resolved = contained(path, media_dir)
    return {"sha256": digest_file(resolved), "size_bytes": resolved.stat().st_size,
            "suffix": resolved.suffix.lower()}


def freeze_capsule(job, recipe: dict[str, Any], image: str | Path, caption: str | Path,
                   media_dir: str | Path) -> dict[str, Any]:
    """Freeze verified Character artifacts only after their job has completed."""
    recipe = validate_recipe(recipe)
    if recipe["job_id"] != job.id:
        raise ValueError("Character recipe does not belong to this job")
    image, caption = contained(image, media_dir), contained(caption, media_dir)
    recorded_caption = job.meta.get("character_caption")
    if not isinstance(recorded_caption, str) or contained(recorded_caption, media_dir) != caption:
        raise ValueError("Character caption does not match the job artifact")
    if image.suffix.lower() != ".png" or caption.suffix.lower() != ".txt":
        raise ValueError("Character Capsule requires a PNG image and TXT caption")
    if not image.stat().st_size:
        raise ValueError("Character image must be non-empty")
    try:
        resolved_caption = caption.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Character caption must be UTF-8 text") from exc
    if not resolved_caption.strip():
        raise ValueError("Character caption must be non-empty")
    if job.engine != ENGINE or not job.result:
        raise ValueError("A Character image result is required")
    result = contained(job.result, media_dir)
    if result != image:
        raise ValueError("Character job result does not match the frozen image")
    assets = {"image": _asset(image, media_dir), "caption": _asset(caption, media_dir)}
    if recipe.get("face_refine") is True:
        base = contained(job.meta.get("character_base_image", ""), media_dir)
        if base == image or base.suffix.lower() != ".png" or not base.stat().st_size:
            raise ValueError("Character base image must be a separate non-empty PNG")
        from character_pipeline import _validate_png
        if _validate_png(base, recipe["mode"]) != _validate_png(image, recipe["mode"]):
            raise ValueError("Character base image dimensions differ from the refined image")
        assets["base_image"] = _asset(base, media_dir)
    capsule = {
        "format": CAPSULE_FORMAT,
        "schema_version": recipe["schema_version"] if recipe["schema_version"] in (6, 7) else 2,
        "job_id": job.id,
        "parent_job_id": job.meta.get("parent_job_id"),
        "engine": ENGINE,
        "recipe": recipe,
        "recipe_sha256": digest_json(recipe),
        "assets": assets,
        "resolved_caption": resolved_caption,
        "replay": {
            "contract": REPLAY_CONTRACT,
            "model_weights_hashed": False,
        },
    }
    capsule["capsule_id"] = "sha256:" + digest_json(capsule)
    job.meta["character_recipe"] = copy.deepcopy(recipe)
    job.meta["character_caption"] = str(caption)
    job.meta["character_capsule"] = copy.deepcopy(capsule)
    return copy.deepcopy(capsule)


def _validate_asset_metadata(value: Any, suffix: str) -> None:
    if not isinstance(value, dict) or set(value) != {"sha256", "size_bytes", "suffix"}:
        raise ValueError("The frozen Character artifact metadata changed")
    if (not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
            or type(value["size_bytes"]) is not int or value["size_bytes"] <= 0
            or value["suffix"] != suffix):
        raise ValueError("The frozen Character artifact metadata changed")


def _validate_capsule_shape(capsule: dict[str, Any], job) -> None:
    version = capsule.get("schema_version")
    if type(version) is not int:
        raise ValueError("The frozen Character capsule schema is unsupported")
    common = {"format", "schema_version", "job_id", "parent_job_id", "engine", "recipe",
              "recipe_sha256", "assets", "replay", "capsule_id"}
    if version in LEGACY_CAPSULE_SCHEMA_VERSIONS:
        required = common
    elif version in (2, 6, CAPSULE_SCHEMA_VERSION):
        required = common | {"resolved_caption"}
        if not isinstance(capsule.get("resolved_caption"), str) or not capsule["resolved_caption"].strip():
            raise ValueError("The frozen Character resolved caption changed")
    else:
        raise ValueError("The frozen Character capsule schema is unsupported")
    if set(capsule) != required or capsule.get("format") != CAPSULE_FORMAT:
        raise ValueError("The frozen Character capsule format changed")
    if capsule.get("engine") != ENGINE or capsule.get("job_id") != job.id:
        raise ValueError("Character capsule identity mismatch")
    parent = capsule.get("parent_job_id")
    if parent is not None and (not isinstance(parent, str) or not _JOB_ID.fullmatch(parent)):
        raise ValueError("The frozen Character capsule lineage changed")
    replay = capsule.get("replay")
    if (not isinstance(replay, dict)
            or replay != {"contract": REPLAY_CONTRACT, "model_weights_hashed": False}
            or replay.get("model_weights_hashed") is not False):
        raise ValueError("The frozen Character replay contract changed")
    recipe = capsule.get("recipe")
    # Legacy envelopes predate recipes 6/7; they must never hide future contracts.
    allowed_recipes = allowed_recipe_versions(version)
    if (not isinstance(recipe, dict) or type(recipe.get("schema_version")) is not int
            or recipe["schema_version"] not in allowed_recipes):
        raise ValueError("The frozen Character recipe contract changed")
    assets = capsule.get("assets")
    roles = {"image", "caption"}
    if version in (6, 7):
        if type(recipe.get("face_refine")) is not bool:
            raise ValueError("The frozen Character recipe contract changed")
        if recipe["face_refine"]:
            roles.add("base_image")
    if not isinstance(assets, dict) or set(assets) != roles:
        raise ValueError("The frozen Character artifact list changed")
    if "base_image" in roles:
        _validate_asset_metadata(assets["base_image"], ".png")
    _validate_asset_metadata(assets["image"], ".png")
    _validate_asset_metadata(assets["caption"], ".txt")


def get_capsule(job) -> dict[str, Any]:
    """Read historical evidence without applying current recipe policy."""
    if job.engine != ENGINE or job.status != "done" or not job.result:
        raise ValueError("A completed Character result is required")
    capsule = copy.deepcopy(job.meta.get("character_capsule"))
    if not isinstance(capsule, dict):
        raise ValueError("No frozen Character capsule exists")
    _validate_capsule_shape(capsule, job)
    identifier = capsule.pop("capsule_id")
    if identifier != "sha256:" + digest_json(capsule):
        raise ValueError("The frozen Character capsule changed")
    capsule["capsule_id"] = identifier
    if capsule.get("engine") != ENGINE or capsule.get("job_id") != job.id:
        raise ValueError("Character capsule identity mismatch")
    recipe = capsule.get("recipe")
    if (not isinstance(recipe, dict) or recipe.get("job_id") != job.id
            or capsule.get("recipe_sha256") != digest_json(recipe)):
        raise ValueError("The frozen Character recipe changed")
    validate_frozen_recipe(recipe)
    return capsule


def replay_recipe(job, media_dir: str | Path) -> dict[str, Any]:
    """Validate current policy and local artifact bytes before a replay submission."""
    capsule = get_capsule(job)
    try:
        recipe = validate_current_recipe(capsule["recipe"])
    except ValueError as exc:
        raise ValueError("This Character was frozen with an earlier policy; create a new Character instead of replaying it.") from exc
    image = contained(job.result, media_dir)
    caption = contained(job.meta.get("character_caption", ""), media_dir)
    paths = [(image, "image"), (caption, "caption")]
    if recipe.get("face_refine") is True:
        base = contained(job.meta.get("character_base_image", ""), media_dir)
        if base == image or base.suffix.lower() != ".png":
            raise ValueError("A Character base image changed after the capsule was frozen")
        paths.append((base, "base_image"))
    for path, role in paths:
        expected = capsule["assets"].get(role)
        if not isinstance(expected, dict) or expected.get("sha256") != digest_file(path) \
                or expected.get("size_bytes") != path.stat().st_size or expected.get("suffix") != path.suffix.lower():
            raise ValueError("A Character input changed after the capsule was frozen")
    return copy.deepcopy(recipe)
