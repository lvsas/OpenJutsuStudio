"""Say whether this machine can run the studio, before anyone tries.

A judge should never discover a missing node pack in the middle of a generation.
This script checks the same things a careful person would check by hand, prints one
line per check, and exits non-zero when something required is absent.

    python scripts/validate_install.py                      # the app only
    python scripts/validate_install.py --comfyui /path/to/ComfyUI
    python scripts/validate_install.py --comfyui /path --comfy http://127.0.0.1:8188
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _required_packs(manifest: dict) -> list[str]:
    return [pack['name'] for pack in manifest.get('comfyui_packs', [])
            if pack.get('required') and pack.get('name')]


def inspect(root: Path = ROOT, comfyui: Path | None = None) -> dict:
    """Collect facts; never raise on a missing prerequisite."""
    root = Path(root)
    checks: dict[str, bool] = {}
    problems: list[str] = []
    missing_packs = 0

    python = root / '.venv' / 'bin' / 'python'
    checks['venv'] = python.exists()
    if not checks['venv']:
        problems.append('no .venv: run make install (or bash scripts/setup.sh --with-proxy)')

    checks['ffmpeg'] = bool(shutil.which('ffmpeg'))
    if not checks['ffmpeg']:
        problems.append('ffmpeg is not on PATH: install it before rendering')

    manifest = {}
    manifest_path = root / 'dependencies.json'
    try:
        manifest = json.loads(manifest_path.read_text())
        checks['manifest'] = isinstance(manifest, dict) and bool(manifest)
    except (OSError, json.JSONDecodeError):
        checks['manifest'] = False
    if not checks['manifest']:
        problems.append('dependencies.json is missing or unreadable')

    if comfyui is None:
        checks['custom_nodes'] = True
    else:
        custom_nodes = Path(comfyui) / 'custom_nodes'
        checks['custom_nodes'] = custom_nodes.is_dir()
        if not checks['custom_nodes']:
            problems.append(f'{comfyui} has no custom_nodes directory')
        elif checks['manifest']:
            required = _required_packs(manifest)
            missing = [name for name in required if not (custom_nodes / name).is_dir()]
            missing_packs = len(missing)
            if missing:
                problems.append(f'{missing_packs} required pack(s) missing: ' + ', '.join(missing))

    work = root / 'work'
    try:
        work.mkdir(parents=True, exist_ok=True)
        probe = work / '.validate-write'
        probe.write_text('ok')
        probe.unlink()
        checks['work'] = True
    except OSError:
        checks['work'] = False
        problems.append('work/ is not writable: the app cannot store takes or media')

    return {'checks': checks, 'problems': problems, 'missing_packs': missing_packs}


def probe_app(url: str) -> dict:
    """Ask a running studio what it is missing; absence is not a failure."""
    endpoint = url.rstrip('/') + '/api/readiness'
    try:
        with urllib.request.urlopen(endpoint, timeout=5) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='repository root')
    parser.add_argument('--comfyui', type=Path, default=None, help='ComfyUI root to inspect')
    parser.add_argument('--comfy', default=None, help='running executor URL to probe with check_dependencies')
    parser.add_argument('--app', default=None,
                        help='running studio URL to ask what it reports as missing')
    parser.add_argument('--json', action='store_true', help='machine-readable output')
    args = parser.parse_args(argv)

    report = inspect(args.root, args.comfyui)
    for name, ok in report['checks'].items():
        print(f'{"ok      " if ok else "MISSING "} {name}')
    for problem in report['problems']:
        print(f'  - {problem}')

    if args.comfy:
        checker = Path(args.root) / 'scripts' / 'check_dependencies.py'
        if checker.is_file():
            completed = subprocess.run([sys.executable, str(checker), '--host', args.comfy,
                                        '--engine', 'all'], capture_output=True, text=True)
            tail = (completed.stdout or completed.stderr).strip().splitlines()[-3:]
            for line in tail:
                print(f'  executor: {line}')
            if completed.returncode != 0:
                report['problems'].append('the executor is missing node classes or weights')

    if args.app:
        readiness = probe_app(args.app)
        if not readiness:
            print(f'note     the studio at {args.app} is not answering; start it with make run')
        else:
            nodes = readiness.get('missing_nodes') or []
            models = readiness.get('missing_models') or []
            print(f'{"ok      " if readiness.get("ready") else "MISSING "} studio readiness')
            if nodes:
                print('  - missing node classes: ' + ', '.join(map(str, nodes)))
                report['problems'].append('the studio reports missing node classes')
            if models:
                print('  - missing weights: ' + ', '.join(map(str, models)))
                report['problems'].append('the studio reports missing weights')

    if args.json:
        print(json.dumps(report, indent=2))
    return 0 if not report['problems'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
