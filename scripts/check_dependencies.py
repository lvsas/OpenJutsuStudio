#!/usr/bin/env python3
"""Check what a ComfyUI machine is missing for this application.

Reads `dependencies.json` and asks the target's `/object_info`, then reports, per category, what is
absent. Exits non-zero when something required is missing, so it can gate a deployment.

    python3 scripts/check_dependencies.py --host http://127.0.0.1:8188
    python3 scripts/check_dependencies.py --host <url> --include-planned   # also the FLUX 3 set
    python3 scripts/check_dependencies.py --host <url> --json             # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

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
    node_info = object_info.get(node) or {}
    for section in ("required", "optional"):
        spec = (node_info.get("input") or {}).get(section, {}).get(field)
        if not isinstance(spec, list) or not spec:
            continue
        first = spec[0]
        if isinstance(first, list):
            return [value for value in first if isinstance(value, str)]
        if isinstance(first, str) and first.upper() == "COMBO":
            second = spec[1] if len(spec) > 1 else {}
            if isinstance(second, dict) and isinstance(second.get("options"), list):
                return [value for value in second["options"] if isinstance(value, str)]
        if isinstance(first, dict) and isinstance(first.get("options"), list):
            return [value for value in first["options"] if isinstance(value, str)]
    return []


def all_model_files(object_info):
    """Every model file the machine reports, across the loaders we know how to read."""
    files = set()
    for node, field in set(LOADER_FIELD.values()):
        files.update(loader_options(object_info, node, field))
    return files


def check(object_info, manifest, include_planned=False):
    """Return a report dict. Pure, so a test can drive it with a synthetic inventory."""
    report = {"missing_nodes": {}, "present_packs": [], "missing_models": [],
              "missing_core_nodes": [], "planned_roles": [], "checked_models": 0}

    for pack in manifest.get("comfyui_packs", []):
        present = [node for node in pack["nodes"] if node in object_info]
        absent = [node for node in pack["nodes"] if node not in object_info]
        if absent:
            modules = sorted({(object_info.get(node) or {}).get("python_module", "")
                              for node in present if object_info.get(node)})
            report["missing_nodes"][pack["name"]] = {
                "missing": absent, "present": present, "resolved_module": modules}
        else:
            report["present_packs"].append(pack["name"])

    # Core nodes carry a version floor: a miss means ComfyUI is too old rather than incomplete.
    core_missing = [node for node in manifest.get("core_nodes", {}).get("from_comfy_extras", [])
                    if node not in object_info]
    report["missing_core_nodes"] = core_missing

    entries = list(manifest.get("models", [])) + list(manifest.get("loras", []))

    for entry in entries:
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
    if include_planned:
        machine_files = all_model_files(object_info)
        for role in manifest.get("character_generator", {}).get("roles", []):
            alternatives = role.get("alternatives", [])
            found = [name for name in alternatives if name in machine_files]
            report["planned_roles"].append({
                "role": role["role"], "satisfied": bool(found), "matched": found,
                "alternatives": alternatives, "note": role.get("note", "")})
    return report


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
            print(f"  role {entry['role']:<18} MISSING — needs one of: "
                  f"{', '.join(entry['alternatives'])}")
    if not report["missing_nodes"] and not report["missing_models"] \
            and not report["missing_core_nodes"]:
        print("everything required is present")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="http://127.0.0.1:8188",
                        help="base URL of the ComfyUI to check")
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--include-planned", action="store_true",
                        help="also check the models the character generator will need")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    try:
        object_info = fetch_object_info(args.host)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"cannot reach {args.host}: {exc}", file=sys.stderr)
        return 2

    report = check(object_info, manifest, include_planned=args.include_planned)
    print_report(report, as_json=args.json)

    required_missing = bool(report["missing_nodes"]) or bool(report["missing_core_nodes"]) or \
        any(not item.get("planned") for item in report["missing_models"])
    return 1 if required_missing else 0


if __name__ == "__main__":
    sys.exit(main())
