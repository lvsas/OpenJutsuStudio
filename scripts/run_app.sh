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
# Do not inherit a Cloud target from the interactive shell. The local proxy is the
# only default; a different self-hosted proxy needs an explicit application override.
export COMFY_BASE_URL="${OPENGENJUTSU_COMFY_BASE_URL:-http://127.0.0.1:8189}"

# Loopback is the default bind. A single explicit interface address is allowed for a
# trusted LAN or a tunnel; wildcard binds are refused so the app is never exposed on
# every interface by accident, and the app has no built-in authentication.
HOST="${OPENGENJUTSU_HOST:-127.0.0.1}"
case "$HOST" in
  0.0.0.0|::|\[::\])
    printf 'Refusing wildcard bind (%s). Set OPENGENJUTSU_HOST to one explicit trusted address.\n' "$HOST" >&2
    exit 1
    ;;
esac

exec .venv/bin/python -m uvicorn src.app:app \
  --app-dir "$ROOT" \
  --host "$HOST" \
  --port "${OPENGENJUTSU_PORT:-8000}"
