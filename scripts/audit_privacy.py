"""Look for anything private that a visitor could reach, on three surfaces.

The repository is public the moment it stops being private, and a path or a token
that nobody re-checked is a permanent leak in the history. This script makes the
check repeatable instead of a memory exercise:

    python scripts/audit_privacy.py            # files in the current tree
    python scripts/audit_privacy.py --history  # every object reachable from any ref
    python scripts/audit_privacy.py --refs     # per branch, which ref exposes what

It exits 1 on a finding. Intentional matches are declared in
`docs/audit-allowlist.txt`, one `path|pattern|reason` per line, so an exception is
reviewed rather than silent.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / 'docs' / 'audit-allowlist.txt'

PATTERNS = {
    # Placeholders used by tests are not personal paths; a real account name is.
    'home-path': re.compile(r'/home/(?!user/|example/|you/|yourname/|test/)[A-Za-z0-9._-]+/'),
    'private-ipv4': re.compile(r'(?<![\w.])(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?![\w.])'),
    'api-key': re.compile(r'sk-[A-Za-z0-9]{20,}'),
    'github-token': re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'),
    'aws-key': re.compile(r'AKIA[0-9A-Z]{16}'),
    'private-key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'email': re.compile(r'[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com|example\.(?:com|org))[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
}


def git(*args: str, binary: bool = False):
    try:
        return subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True,
                              text=not binary, check=True)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or b'').decode('utf-8', 'replace').strip().splitlines()
        hint = detail[-1] if detail else f'git exited {error.returncode}'
        if 'dubious ownership' in ' '.join(detail):
            hint += ' — run: git config --global --add safe.directory ' + str(ROOT)
        raise SystemExit(f'git could not read this repository: {hint}') from None


def load_allowlist() -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    if not ALLOWLIST.is_file():
        return allowed
    for line in ALLOWLIST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [part.strip() for part in line.split('|')]
        if len(parts) >= 2:
            allowed.add((parts[0], parts[1]))
    return allowed


def scan(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for name, pattern in PATTERNS.items():
        hits = pattern.findall(text)
        if hits:
            found[name] = sorted({hit if isinstance(hit, str) else hit[0] for hit in hits})[:5]
    return found


def tree_files() -> list[str]:
    raw = git('ls-files', '-z', binary=True).stdout
    return [name for name in raw.decode().split('\0') if name]


def read_worktree(path: str) -> str | None:
    try:
        data = (ROOT / path).read_bytes()
    except OSError:
        return None
    if b'\0' in data[:4096]:
        return None
    return data.decode('utf-8', errors='ignore')


def audit_tree() -> list[str]:
    findings = []
    allowed = load_allowlist()
    for path in tree_files():
        text = read_worktree(path)
        if text is None:
            continue
        for name, hits in scan(text).items():
            if (path, name) in allowed:
                continue
            findings.append(f'{path}: {name} -> {", ".join(hits)}')
    return findings


def has_origin() -> bool:
    return 'origin' in git('remote').stdout.split()


def scope() -> str:
    """What a visitor can actually reach: the remote refs, unless told otherwise."""
    if os.environ.get('AUDIT_INCLUDE_LOCAL') or not has_origin():
        return '--all'
    return '--remotes=origin'


def all_blobs() -> dict[str, str]:
    """blob sha -> a path that shows it, across the published refs."""
    raw = git('rev-list', '--objects', scope()).stdout
    blobs: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split(' ', 1)
        if len(parts) == 2:
            sha, path = parts
            if sha not in blobs:
                blobs[sha] = path
    return blobs


def audit_history() -> list[str]:
    findings = []
    allowed = load_allowlist()
    for sha, path in all_blobs().items():
        kind = git('cat-file', '-t', sha).stdout.strip()
        if kind != 'blob':
            continue
        if not path.endswith(('.py', '.md', '.json', '.js', '.html', '.css', '.yml', '.yaml',
                              '.sh', '.txt', '.toml', '.cfg', '.ini', '.service', '')):
            continue
        data = git('cat-file', '-p', sha, binary=True).stdout
        if b'\0' in data[:4096]:
            continue
        text = data.decode('utf-8', errors='ignore')
        for name, hits in scan(text).items():
            if (path, name) in allowed:
                continue
            findings.append(f'{path} (object {sha[:8]}): {name} -> {", ".join(hits)}')
    return findings


def audit_refs() -> list[str]:
    findings = []
    allowed = load_allowlist()
    refs = git('for-each-ref', '--format=%(refname)',
               *(['refs/remotes/origin'] if has_origin() and not os.environ.get('AUDIT_INCLUDE_LOCAL')
                 else ['refs/heads', 'refs/remotes'])).stdout.split()
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        listing = git('ls-tree', '-r', ref).stdout
        for line in listing.splitlines():
            meta, path = line.split('\t', 1)
            parts = meta.split()
            if len(parts) < 3 or parts[1] != 'blob':
                continue
            sha = parts[2]
            if (sha, path) in seen:
                continue
            seen.add((sha, path))
            data = git('cat-file', '-p', sha, binary=True).stdout
            if b'\0' in data[:4096]:
                continue
            text = data.decode('utf-8', errors='ignore')
            for name, hits in scan(text).items():
                if (path, name) in allowed:
                    continue
                findings.append(f'{ref} {path}: {name} -> {", ".join(hits)}')
    return findings


def main(argv=None) -> int:
    if not shutil.which('git'):
        print('git is required: the audit reads the index and the object database.',
              file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='scan every object reachable from any ref')
    parser.add_argument('--refs', action='store_true', help='scan each ref separately')
    args = parser.parse_args(argv)

    surfaces = []
    if args.history:
        surfaces.append(('history', audit_history))
    if args.refs:
        surfaces.append(('refs', audit_refs))
    if not surfaces:
        surfaces.append(('tree', audit_tree))

    status = 0
    for name, run in surfaces:
        findings = run()
        print(f'== {name}')
        if findings:
            status = 1
            for finding in findings:
                print(f'  LEAK {finding}')
        else:
            print('  clean')
    return status


if __name__ == '__main__':
    raise SystemExit(main())
