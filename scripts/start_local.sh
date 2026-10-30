#!/usr/bin/env bash
# One command to run the studio: the local SDK proxy, then the app.
#
# The application speaks the Comfy SDK v2 API; a stock ComfyUI server does not,
# so a loopback proxy translates between them. Starting two processes by hand is
# the part people get wrong, so this script does it in the right order and stops
# the proxy again if it started it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${OPENGENJUTSU_PORT:-8000}"
COMFY="${OPENGENJUTSU_COMFY_URL:-http://127.0.0.1:8188}"
PROXY_ADDR="${OPENGENJUTSU_PROXY_ADDR:-127.0.0.1:8189}"
PROXY_HOST="${PROXY_ADDR%%:*}"
PROXY_PORT="${PROXY_ADDR##*:}"
PROXY_BIN="$ROOT/.venv/bin/comfy-api-proxy"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  printf 'No .venv yet. Run: bash scripts/setup.sh --with-proxy\n' >&2
  exit 1
fi

listening() { (exec 3<>"/dev/tcp/${1%%:*}/${1##*:}") 2>/dev/null; }

STARTED_PROXY=0
cleanup() {
  if [[ "$STARTED_PROXY" == 1 && -n "${PROXY_PID:-}" ]]; then
    kill "$PROXY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if listening "$PROXY_ADDR"; then
  printf 'SDK proxy already listening on %s\n' "$PROXY_ADDR"
elif [[ -x "$PROXY_BIN" ]]; then
  mkdir -p work
  printf 'Starting SDK proxy on %s -> %s\n' "$PROXY_ADDR" "$COMFY"
  env -u PYTHONPATH "$PROXY_BIN" run --comfyui "$COMFY" --host "$PROXY_HOST" --port "$PROXY_PORT" \
    >work/proxy.log 2>&1 &
  PROXY_PID=$!
  STARTED_PROXY=1
  for _ in $(seq 1 60); do
    listening "$PROXY_ADDR" && break
    sleep 0.25
  done
  if ! listening "$PROXY_ADDR"; then
    printf 'The proxy did not come up. Last lines of work/proxy.log:\n' >&2
    tail -20 work/proxy.log >&2 || true
    exit 1
  fi
else
  printf 'comfy-api-proxy is not installed. Run: bash scripts/setup.sh --with-proxy\n' >&2
  printf 'If you already have an SDK v2 endpoint, point OPENGENJUTSU_COMFY_BASE_URL at it.\n' >&2
  exit 1
fi

printf 'Studio: http://127.0.0.1:%s\n' "$PORT"
OPENGENJUTSU_COMFY_BASE_URL="http://$PROXY_ADDR" \
  exec bash "$ROOT/scripts/run_app.sh"
