#!/usr/bin/env python3
"""Plan declared Swap models; only --download permits installation."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
from model_catalog import roles
from model_download import fetch, relative_name, source_contract

FOLDERS = {'UNETLoader': 'diffusion_models', 'CLIPLoader': 'text_encoders',
           'VAELoader': 'vae', 'VAELoaderKJ': 'vae', 'LoraLoaderModelOnly': 'loras',
           'MinimaxH3LatentUpscaler3D': 'latent_upscale_models'}


def build_plan(manifest, engine='all'):
    """Return (resolved items, unresolved labels), using declared defaults only."""
    catalog = {r['key']: r for r in roles()}
    found, unresolved, plan = {}, [], []
    if not isinstance(manifest, dict) or engine not in ('all', 'ltx', 'h3'):
        return [], ['Invalid manifest or engine']
    for section in ('models', 'loras'):
        entries = manifest.get(section, [])
        if not isinstance(entries, list):
            return [], ['Invalid manifest section']
        for entry in entries:
            if not isinstance(entry, dict):
                unresolved.append('Invalid manifest entry')
                continue
            key = entry.get('role_key')
            if key is None:
                continue
            if not isinstance(key, str) or key not in catalog:
                unresolved.append('Unknown role key')
                continue
            found.setdefault(key, []).append(entry)
    for key, role in catalog.items():
        if engine != 'all' and role['engine'] != engine:
            continue
        try:
            entries = found.get(key, [])
            if len(entries) != 1:
                raise ValueError()
            entry = entries[0]
            folder = FOLDERS[role['class_type']]
            if entry.get('file') != role['default'] or entry.get('folder') != folder:
                raise ValueError()
            relative = relative_name(folder + '/' + entry['file'])
            source_contract(entry.get('download'))
            plan.append({'role_key': key, 'relative': relative, 'download': dict(entry['download'])})
        except (ValueError, TypeError, KeyError):
            unresolved.append(key)
    return plan, unresolved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfyui', required=True, help='Explicit ComfyUI root (models must exist for downloads)')
    parser.add_argument('--engine', choices=('ltx', 'h3', 'all'), default='all')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'dependencies.json')
    parser.add_argument('--download', action='store_true', help='Explicitly permit network and model writes')
    parser.add_argument('--dry-run', action='store_true', help='Plan only, even with --download')
    args = parser.parse_args(argv)
    try:
        plan, unresolved = build_plan(json.loads(args.manifest.read_text()), args.engine)
    except (OSError, ValueError, RecursionError):
        print('ERROR: Cannot read model manifest.')
        return 1
    for item in plan:
        source = item['download']
        size = source.get('size_bytes', 'unknown')
        integrity = 'SHA-256 verified on install' if source.get('sha256') else 'declared provenance only; no upstream hash'
        print(f"PLAN {item['role_key']} -> models/{item['relative']} | {source['url']} | bytes={size} | {integrity}")
        if source.get('access') == 'gated':
            print('ACCESS GATED: obtain this exact file through your authorized upstream account first; '
                  'place it at the planned destination. This CLI does not accept credentials.')
    for label in unresolved:
        print(f'UNRESOLVED {label}: missing, duplicate or invalid installation contract/source')
    if unresolved:
        return 1  # Never install a partial plan.
    if not args.download or args.dry_run:
        print('Plan only; no network or model writes. Use --download to install.')
        return 0
    failed = False
    for item in plan:
        try:
            print(f"{item['role_key']}: {fetch(item, args.comfyui)}")
        except ValueError as error:
            print(f"{item['role_key']}: {error}")
            failed = True
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
