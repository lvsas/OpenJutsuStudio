"""Install the ComfyUI node packs this app needs, from the declared manifest.

`dependencies.json` already lists every pack with a source and, when the pack is
published on the Comfy registry, a pinned archive and its SHA-256. Nothing used
those entries, so a new machine had to clone them by hand. This script reads the
manifest and installs exactly what it declares, into an existing ComfyUI:

    python scripts/install_executor.py --comfyui /path/to/ComfyUI            # plan
    python scripts/install_executor.py --comfyui /path/to/ComfyUI --install  # act

It never deletes or overwrites an existing pack directory, never touches models
(see scripts/download_models.py), and refuses an archive whose hash does not match
the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_packs(manifest: Path) -> list[dict]:
    data = json.loads(manifest.read_text())
    packs = data.get('comfyui_packs') or []
    if not isinstance(packs, list):
        raise ValueError('comfyui_packs must be a list')
    return packs


def plan(packs: list[dict], comfyui: Path) -> list[dict]:
    """What would happen, without touching the disk."""
    plan_rows = []
    for pack in packs:
        name = pack.get('name')
        if not name:
            raise ValueError('a pack has no name')
        target = comfyui / 'custom_nodes' / name
        install = pack.get('install') or {}
        kind = install.get('kind') or ('git' if pack.get('source') else 'none')
        state = 'present' if target.exists() else ('missing' if kind != 'none' else 'unavailable')
        plan_rows.append({
            'name': name,
            'target': target,
            'state': state,
            'kind': kind,
            'required': bool(pack.get('required')),
            'source': pack.get('source'),
            'package_url': install.get('package_url'),
            'package_sha256': install.get('package_sha256'),
            'nodes': pack.get('nodes') or [],
        })
    return plan_rows


def _digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def install_registry(row: dict) -> None:
    url = row['package_url']
    if not url:
        raise ValueError(f'{row["name"]}: no package_url to install from')
    with urllib.request.urlopen(url, timeout=120) as response:
        blob = response.read()
    expected = (row.get('package_sha256') or '').lower()
    if expected and _digest(blob) != expected:
        raise ValueError(f'{row["name"]}: archive hash does not match the manifest')
    target = row['target']
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + '.install-tmp')
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for member in archive.namelist():
            destination = (staging / member).resolve()
            if not destination.is_relative_to(staging.resolve()):
                raise ValueError(f'{row["name"]}: archive escapes the pack directory')
        archive.extractall(staging)
    # registry archives usually wrap the pack in one top folder
    entries = [entry for entry in staging.iterdir()]
    source = entries[0] if len(entries) == 1 and entries[0].is_dir() else staging
    source.rename(target)
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)


def install_git(row: dict) -> None:
    subprocess.run(['git', 'clone', '--depth', '1', row['source'], str(row['target'])],
                   check=True, capture_output=True, text=True, timeout=600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfyui', required=True, help='ComfyUI root that contains custom_nodes')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'dependencies.json')
    parser.add_argument('--install', action='store_true', help='explicitly permit network and writes')
    parser.add_argument('--engine', choices=('ltx', 'h3', 'all'), default='all')
    args = parser.parse_args()

    comfyui = Path(args.comfyui).expanduser().resolve()
    if not (comfyui / 'custom_nodes').is_dir():
        print(f'{comfyui} has no custom_nodes directory; point --comfyui at a ComfyUI install.',
              file=sys.stderr)
        return 2

    rows = plan(load_packs(args.manifest), comfyui)
    missing_required = [row for row in rows if row['state'] == 'missing' and row['required']]
    for row in rows:
        marker = {'present': 'ok      ', 'missing': 'MISSING ', 'unavailable': 'no-source'}[row['state']]
        print(f'{marker} {row["name"]:36} {row["kind"]:9} -> {row["target"]}')

    if not args.install:
        print(f'\n{len(missing_required)} required pack(s) missing. '
              'Re-run with --install to download and unpack them.')
        return 1 if missing_required else 0

    failures = []
    for row in missing_required:
        try:
            print(f'installing {row["name"]} ({row["kind"]})')
            if row['kind'] == 'registry':
                install_registry(row)
            elif row['kind'] == 'git':
                install_git(row)
            else:
                raise ValueError('no install recipe')
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failures.append(f'{row["name"]}: {error}')

    for failure in failures:
        print(f'failed: {failure}', file=sys.stderr)
    print('\nRestart ComfyUI so the new node classes are registered, then run:')
    print(f'  python scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine {args.engine}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
