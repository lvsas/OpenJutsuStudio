#!/usr/bin/env bash
# Bootstrap the local OpenGenjutsu environment.
# Usage: bash scripts/setup.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  printf 'Error: uv is required. Install it from https://docs.astral.sh/uv/\n' >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  uv venv .venv --python 3.12
fi

uv pip install --python .venv/bin/python -r requirements.txt
mkdir -p work/jobs work/media

printf '\nSetup complete. Start the app with:\n  bash scripts/run_app.sh\n'
printf 'Open http://127.0.0.1:8000 in your browser.\n'
