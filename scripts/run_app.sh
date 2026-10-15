#!/usr/bin/env bash
# Run the local web app in its project venv, isolated from caller PYTHONPATH.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  printf 'Environment missing. Run: bash scripts/setup.sh\n' >&2
  exit 1
fi

# Hermes and other agent shells may inject packages from an incompatible Python.
unset PYTHONPATH
if ! .venv/bin/python -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'; then
  printf 'Error: .venv must use Python 3.12. See docs/local-setup.md to recreate it safely.\n' >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn src.app:app \
  --app-dir "$ROOT" \
  --host 127.0.0.1 \
  --port "${OPENGENJUTSU_PORT:-8000}"
