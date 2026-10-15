#!/usr/bin/env bash
# Bootstrap the local OpenGenjutsu environment; never start a service or download models.
set -euo pipefail

WITH_PROXY=0
for arg in "$@"; do
  case "$arg" in
    --with-proxy) WITH_PROXY=1 ;;
    -h|--help)
      printf 'Usage: bash scripts/setup.sh [--with-proxy]\n'
      printf 'Requires uv and FFmpeg (ffmpeg + ffprobe); creates a Python 3.12 venv.\n'
      printf 'The optional flag installs comfy-api-proxy; no service is started.\n'
      exit 0 ;;
    *) printf 'Error: unknown option: %s\nSee: bash scripts/setup.sh --help\n' "$arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# Agent shells can inject packages built for a different Python interpreter.
unset PYTHONPATH

if ! command -v uv >/dev/null 2>&1; then
  printf 'Error: uv is required. Install it from https://docs.astral.sh/uv/\n' >&2
  exit 1
fi
for tool in ffmpeg ffprobe; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Error: %s is required. Install FFmpeg (including ffprobe) and retry.\n' "$tool" >&2
    printf 'See docs/local-setup.md for platform-specific prerequisites.\n' >&2
    exit 1
  fi
done

if [[ ! -e .venv && ! -L .venv ]]; then
  uv venv .venv --python 3.12
fi
if [[ ! -x .venv/bin/python ]]; then
  printf 'Error: existing .venv is unusable; inspect/move it manually, then rerun setup.\n' >&2
  printf 'Setup will not replace an existing environment or symlink.\n' >&2
  exit 1
fi
if ! .venv/bin/python -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'; then
  printf 'Error: .venv must use Python 3.12. Inspect/move it manually, then rerun setup.\n' >&2
  exit 1
fi

uv pip install --python .venv/bin/python -r requirements.txt
if [[ "$WITH_PROXY" == 1 ]]; then
  uv pip install --python .venv/bin/python 'comfy-api-proxy==0.1.6'
fi
mkdir -p work/jobs work/media

printf '\nApp environment ready (this does not verify ComfyUI/models).\n'
if [[ "$WITH_PROXY" == 0 ]]; then
  printf 'Need a local SDK proxy? Rerun with --with-proxy to install it explicitly.\n'
fi
printf 'Start the proxy and app separately; see docs/local-setup.md.\n'
printf 'App: bash scripts/run_app.sh\nOpen http://127.0.0.1:8000 in your browser.\n'
