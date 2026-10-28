"""One release-file boundary for checks: Git index, or an unpacked source tree."""
import os
from pathlib import Path, PurePosixPath
import subprocess

ARCHIVES = ('.zip', '.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz')
LOCAL_DIRS = {'.git', '.venv', 'work', 'cache', 'node_modules', '__pycache__'}
TEXT = {'.py', '.js', '.mjs', '.json', '.md', '.html', '.css', '.yaml', '.yml',
        '.sh', '.txt', '.svg'}


def release_files(root):
    root = Path(root)
    indexed = (root / '.git').is_file() or (root / '.git/HEAD').is_file()
    candidates = set()
    if indexed:
        try:
            result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached'],
                                    capture_output=True, check=True, timeout=15)
            if result.returncode != 0:
                raise ValueError('Release inventory unavailable')
            for raw in result.stdout.split(b'\0'):
                if not raw:
                    continue
                name = PurePosixPath(os.fsdecode(raw))
                if name.is_absolute() or '..' in name.parts:
                    raise ValueError('Invalid release inventory')
                candidates.add(root.joinpath(*name.parts))
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError('Release inventory unavailable') from error
    # Always inspect distributable archives, even if not staged yet. In an
    # unpacked source archive there is no Git index: inspect every source file.
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in LOCAL_DIRS)
        for name in files:
            path = Path(directory) / name
            if not indexed or name.lower().endswith(ARCHIVES):
                candidates.add(path)
    for path in sorted(candidates):
        if path.suffix.lower() in TEXT or str(path).lower().endswith(ARCHIVES):
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root):
                raise ValueError('Release file traverses a symbolic link')
            yield path
