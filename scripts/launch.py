"""Start the studio on any platform: Windows, macOS or Linux.

The shell scripts in this directory are the Linux and macOS path. Windows has no
bash, so this launcher does the same three things in Python: check the
environment, start the local SDK proxy if it is not already up, then hand the
terminal to the app. It is deliberately small and dependency-free.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == 'nt'


def venv_bin(name: str) -> Path:
    folder = ROOT / '.venv' / ('Scripts' if WINDOWS else 'bin')
    return folder / (f'{name}.exe' if WINDOWS else name)


def port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def missing_venv_hint() -> str:
    """The interpreter path differs per platform; the hint must follow it."""
    return ('No .venv yet. Run: uv venv --python 3.12, then '
            f'uv pip install --python "{venv_bin('python')}" -r requirements.txt')


def refuse(line: str) -> None:
    print(line, file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    app_host = os.environ.get('OPENGENJUTSU_HOST', '127.0.0.1')
    if app_host in {'0.0.0.0', '::', '[::]'}:
        refuse(f'Refusing wildcard bind ({app_host}). '
               'Set OPENGENJUTSU_HOST to one explicit trusted address.')
    python = venv_bin('python')
    if not python.exists():
        refuse(missing_venv_hint())

    app_port = int(os.environ.get('OPENGENJUTSU_PORT', '8000'))

    proxy_host = os.environ.get('OPENGENJUTSU_PROXY_HOST', '127.0.0.1')
    proxy_port = int(os.environ.get('OPENGENJUTSU_PROXY_PORT', '8189'))
    upstream = os.environ.get('COMFYUI_URL', 'http://127.0.0.1:8188')

    started: subprocess.Popen[bytes] | None = None
    if port_open(proxy_host, proxy_port):
        print(f'SDK proxy already listening on {proxy_host}:{proxy_port}')
    else:
        proxy = venv_bin('comfy-api-proxy')
        if not proxy.exists():
            refuse('comfy-api-proxy is not installed. Run: '
                   'uv pip install --python .venv/bin/python comfy-api-proxy==0.1.6')
        print(f'Starting SDK proxy on {proxy_host}:{proxy_port} -> {upstream}')
        started = subprocess.Popen([str(proxy), 'run', '--comfyui', upstream,
                                    '--host', proxy_host, '--port', str(proxy_port)])
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if port_open(proxy_host, proxy_port):
                break
            if started.poll() is not None:
                refuse('The proxy exited. Start it manually to see why: '
                       'comfy-api-proxy run --comfyui ' + upstream)
            time.sleep(0.25)
        else:
            started.terminate()
            refuse('The proxy did not listen in time.')

    env = dict(os.environ)
    env.setdefault('COMFY_BASE_URL', f'http://{proxy_host}:{proxy_port}')
    print(f'Studio: http://{app_host}:{app_port}')
    try:
        return subprocess.call([str(python), '-m', 'uvicorn', 'src.app:app',
                                '--app-dir', str(ROOT), '--host', app_host,
                                '--port', str(app_port)], env=env, cwd=ROOT)
    finally:
        if started is not None and started.poll() is None:
            started.terminate()


if __name__ == '__main__':
    raise SystemExit(main())
