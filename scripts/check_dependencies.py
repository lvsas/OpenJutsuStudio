#!/usr/bin/env python3
"""Check what a ComfyUI machine is missing for this application.

Reads `dependencies.json` and asks the target's `/object_info`, then reports, per category, what is
absent. Exits non-zero when something required is missing, so it can gate a deployment.

    python3 scripts/check_dependencies.py --host http://127.0.0.1:8188
    python3 scripts/check_dependencies.py --host <url> --include-planned   # also the FLUX 3 set
    python3 scripts/check_dependencies.py --host <url> --feature h3-native-continuity-experimental
    python3 scripts/check_dependencies.py --host <url> --feature characters
    python3 scripts/check_dependencies.py --host <url> --json             # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from comfy_schema import loader_choices

MANIFEST = Path(__file__).resolve().parents[1] / "dependencies.json"

# Which loader field holds the file for each ComfyUI model folder.
LOADER_FIELD = {
    "diffusion_models": ("UNETLoader", "unet_name"),
    "unet": ("UNETLoader", "unet_name"),
    "vae": ("VAELoader", "vae_name"),
    "text_encoders": ("CLIPLoader", "clip_name"),
    "clip": ("CLIPLoader", "clip_name"),
    "loras": ("LoraLoaderModelOnly", "lora_name"),
    # Not a folder in the usual sense: this pack publishes its own loader and its own COMBO,
    # which is the field that actually decides whether the file is usable.
    "upscale_models": ("MinimaxH3LatentUpscaler3D", "model_name"),
}


def load_manifest(path=MANIFEST):
    return json.loads(Path(path).read_text())


def loader_options(object_info, node, field):
    """The COMBO choices of a loader field, i.e. the files the machine actually has.

    ComfyUI has used three shapes for this: a list of strings first, then a list whose first
    element is that list, and now `["COMBO", {"options": [...]}]`. Reading only the old shapes
    reports a file as missing when it is present, so all three are handled and each is tested.
    """
    # Share the runtime parser; unknown inventory remains unmet for this install gate.
    return loader_choices(object_info, node, field) or []


def all_model_files(object_info):
    """Every model file the machine reports, across the loaders we know how to read."""
    files = set()
    for node, field in set(LOADER_FIELD.values()):
        files.update(loader_options(object_info, node, field))
    return files


def check(object_info, manifest, include_planned=False, selected_features=()):
    """Return a report dict. Pure, so a test can drive it with a synthetic inventory."""
    selected = set(selected_features)
    characters = manifest.get("character_generator", {})
    character_features = set(characters.get("used_by", ["characters"]))
    if include_planned:
        selected.update(character_features)
    report = {"missing_nodes": {}, "present_packs": [], "missing_models": [],
              "missing_core_nodes": [], "planned_roles": [], "checked_models": 0,
              "optional_missing_nodes": {}, "selected_features": sorted(selected)}

    for pack in manifest.get("comfyui_packs", []):
        if pack.get("status") == "planned" and not include_planned:
            continue
        present = [node for node in pack["nodes"] if node in object_info]
        absent = [node for node in pack["nodes"] if node not in object_info]
        if absent:
            modules = sorted({(object_info.get(node) or {}).get("python_module", "")
                              for node in present if object_info.get(node)})
            required = pack.get("required", True) or selected.intersection(pack.get("used_by", []))
            category = "missing_nodes" if required else "optional_missing_nodes"
            report[category][pack["name"]] = {
                "missing": absent, "present": present, "resolved_module": modules}
        else:
            report["present_packs"].append(pack["name"])

    # Core nodes carry a version floor: a miss means ComfyUI is too old rather than incomplete.
    core = manifest.get("core_nodes", {})
    core_nodes = [*core.get("from_core", []), *core.get("from_comfy_extras", [])]
    report["missing_core_nodes"] = [node for node in dict.fromkeys(core_nodes)
                                    if node not in object_info]

    entries = list(manifest.get("models", [])) + list(manifest.get("loras", []))

    for entry in entries:
        if entry.get("status") == "planned" and not include_planned:
            continue
        folder = entry["folder"]
        node, field = LOADER_FIELD.get(folder, (None, None))
        if node is None:
            report["missing_models"].append(
                {"file": entry["file"], "reason": f"unknown folder {folder}"})
            continue
        report["checked_models"] += 1
        if entry["file"] not in loader_options(object_info, node, field):
            report["missing_models"].append(
                {"file": entry["file"], "folder": folder, "loader": f"{node}.{field}"})

    # The character generator's files are alternatives, not a set: the quantisation variants of one
    # checkpoint must be satisfied by whichever one is installed, or the checker reports five files
    # missing on a machine that is ready.
    if selected.intersection(character_features) and \
            (include_planned or characters.get("status") != "planned"):
        machine_files = all_model_files(object_info)
        for role in characters.get("roles", []):
            if role.get("status") == "planned" and not include_planned:
                continue
            alternatives = role.get("alternatives", [])
            found = [name for name in alternatives if name in machine_files]
            report["planned_roles"].append({
                "role": role["role"], "satisfied": bool(found), "matched": found,
                "alternatives": alternatives, "note": role.get("note", ""),
                "required": role.get("required", True)})
    return report


def required_missing(report):
    """Use the same readiness verdict for the exit code and the human summary."""
    return bool(report["missing_nodes"] or report["missing_core_nodes"] or report["missing_models"]
                or any(role.get("required", True) and not role["satisfied"]
                       for role in report["planned_roles"]))


def fetch_object_info(host):
    url = host.rstrip("/") + "/object_info"
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.loads(response.read().decode())


def print_report(report, as_json=False):
    if as_json:
        print(json.dumps(report, indent=2))
        return
    print(f"nodes checked      : {len(report['present_packs'])} packs complete, "
          f"{len(report['missing_nodes'])} with gaps")
    for pack, detail in report["missing_nodes"].items():
        print(f"  MISSING from {pack}")
        for node in detail["missing"]:
            print(f"      {node}")
        if detail["resolved_module"]:
            print(f"      (its siblings resolve from {', '.join(detail['resolved_module'])})")
    for pack, detail in report.get("optional_missing_nodes", {}).items():
        print(f"  OPTIONAL {pack}: {', '.join(detail['missing'])}")
    if report["missing_core_nodes"]:
        print(f"  ComfyUI too old for: {', '.join(report['missing_core_nodes'])}")
    print(f"models checked     : {report['checked_models']}")
    for item in report["missing_models"]:
        marker = " (planned)" if item.get("planned") else ""
        print(f"  MISSING {item['file']}{marker}")
    for entry in report.get("planned_roles", []):
        if entry["satisfied"]:
            print(f"  role {entry['role']:<18} ok — {entry['matched'][0]}")
        else:
            marker = "MISSING" if entry.get("required", True) else "OPTIONAL"
            print(f"  role {entry['role']:<18} {marker} — needs one of: "
                  f"{', '.join(entry['alternatives'])}")
    if not required_missing(report):
        print("everything required is present")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="http://127.0.0.1:8188",
                        help="base URL of the ComfyUI to check")
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--include-planned", action="store_true",
                        help="include planned dependencies and select character-generator roles")
    parser.add_argument("--feature", action="append", default=[],
                        help="add requirements for a manifest used_by feature "
                             "(repeatable; baseline remains checked)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    features = {feature for pack in manifest.get("comfyui_packs", [])
                for feature in pack.get("used_by", [])}
    features.update(manifest.get("character_generator", {}).get("used_by", ["characters"]))
    if set(args.feature) - features:
        parser.error(f"unknown feature; choose from: {', '.join(sorted(features))}")
    try:
        object_info = fetch_object_info(args.host)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"cannot reach {args.host}: {exc}", file=sys.stderr)
        return 2

    report = check(object_info, manifest, include_planned=args.include_planned,
                   selected_features=args.feature)
    print_report(report, as_json=args.json)

    return 1 if required_missing(report) else 0


if __name__ == "__main__":
    sys.exit(main())
