"""Confined, streaming CPU family I/O; no tensor runtime or SDK imports."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import uuid

from ._contract.timeline_artifacts import ArtifactValidationError, validate_h3_artifact_set

ROLES = ('video', 'mctx', 'conditioning')
NAMES = ('take.mp4', 'take.mctx.safetensors', 'take.cond.safetensors')
SUFFIXES = ('.mp4', '.mctx.safetensors', '.cond.safetensors')
PACK_DIRECTORY = 'opengenjutsu_continuity'
_COMPONENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,199}\Z')
_FAMILY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')
BLOCK_BYTES = 1024 * 1024


class ContinuityError(ValueError):
    """Only stable, path-free adapter errors cross the node boundary."""


def _error(code):
    return ContinuityError(code)


@contextmanager
def safe_errors():
    try:
        yield
    except ArtifactValidationError as exc:
        raise _error(f'{exc.code}: {exc.role}') from None
    except ContinuityError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        # Never expose paths from OS, FFprobe, supplied filenames or metadata.
        raise _error('filesystem_error') from None


def roots():
    # Native Comfy API, deliberately lazy so off-Comfy imports need no stub.
    import folder_paths
    return (Path(folder_paths.get_input_directory()).resolve(strict=True),
            Path(folder_paths.get_output_directory()).resolve(strict=True))


def _relative(value, root, absolute_allowed):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise _error('unsafe_path')
    candidate = Path(value)
    if candidate.is_absolute():
        if not absolute_allowed:
            raise _error('unsafe_path')
        try:
            value = candidate.relative_to(root).as_posix()
        except ValueError:
            raise _error('unsafe_path') from None
    parts = value.split('/')
    if not parts or any(not _COMPONENT.fullmatch(p) or p.endswith((' ', '.')) for p in parts):
        raise _error('unsafe_path')
    return '/'.join(parts)


def _open_regular(root_fd, relative):
    """Walk every component using dir_fd + NOFOLLOW; never follow a symlink."""
    directory = os.dup(root_fd)
    try:
        parts = relative.split('/')
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise _error('not_regular_file')
        return fd
    finally:
        os.close(directory)


def _fingerprint(fd):
    info = os.fstat(fd)
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _blocks(fd):
    """Bound work to the opened file's size; reject growth or truncation."""
    remaining = os.fstat(fd).st_size
    os.lseek(fd, 0, os.SEEK_SET)
    while remaining:
        block = os.read(fd, min(remaining, BLOCK_BYTES))
        if not block:
            raise _error('artifact_changed')
        remaining -= len(block)
        yield block
    if os.read(fd, 1):
        raise _error('artifact_changed')


def _digest(fd):
    digest = hashlib.sha256()
    for block in _blocks(fd):
        digest.update(block)
    return digest.hexdigest()


@contextmanager
def _sources(root, values, absolute_allowed):
    relative = [_relative(value, root, absolute_allowed) for value in values]
    if any(not path.endswith(suffix) for path, suffix in zip(relative, SUFFIXES)):
        raise _error('unsupported_suffix')
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    files = []
    try:
        for path in relative:
            files.append(_open_regular(root_fd, path))
        snapshots = [_fingerprint(fd) for fd in files]
        # The shared validator is unchanged: all versions, structures, geometry,
        # hashes, identity association and repeated stability reads are reused.
        family = validate_h3_artifact_set(*relative, root=root)
        hashes = {asset.role: asset.sha256 for asset in family.assets}

        def check():
            for fd, before, role, path in zip(files, snapshots, ROLES, relative):
                current = _open_regular(root_fd, path)
                try:
                    if (_fingerprint(current) != before or _fingerprint(fd) != before
                            or _digest(fd) != hashes[role] or _fingerprint(fd) != before):
                        raise _error('artifact_changed')
                finally:
                    os.close(current)
        check()
        yield relative, files, family, hashes, check
        check()
    finally:
        for fd in files:
            os.close(fd)
        os.close(root_fd)


def _descriptors(relative):
    return [{'filename': Path(path).name,
             'subfolder': '' if Path(path).parent == Path('.') else Path(path).parent.as_posix(),
             'type': 'output'} for path in relative]


def _result(relative, family, clip):
    return {'ui': {'files': _descriptors(relative)},
            'result': (clip, json.dumps(family.to_manifest(), sort_keys=True, separators=(',', ':')))}


def publish(video, mctx, conditioning):
    with safe_errors():
        _, output = roots()
        with _sources(output, (video, mctx, conditioning), True) as (relative, _, family, _, check):
            # Only expose the optional stock-loader clip when adjacency is real.
            radical = relative[0][:-4]
            clip = relative[0] if relative[1:] == [radical + SUFFIXES[1], radical + SUFFIXES[2]] else ''
            check()
            return _result(relative, family, clip)


def publish_clip(clip):
    """Publish the exact native saver's returned clip, never a guessed counter.

    Verified stock conventions: mctx.sidecar_path / condstore.cond_path
    replace the final .mp4 suffix with .mctx.safetensors / .cond.safetensors.
    The complete family is still opened, hashed and validated by publish().
    """
    with safe_errors():
        _, output = roots()
        video = _relative(clip, output, True)
        if not video.endswith('.mp4'):
            raise _error('unsupported_suffix')
        radical = video[:-4]
        return publish(video, radical + SUFFIXES[1], radical + SUFFIXES[2])


def _copy_file(source_fd, directory_fd, name):
    """Exclusive destination creation and fixed-memory stream, never tensor load."""
    destination = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=directory_fd)
    try:
        for block in _blocks(source_fd):
            view = memoryview(block)
            while view:
                written = os.write(destination, view)
                if written <= 0:
                    raise _error('copy_failed')
                view = view[written:]
        os.fsync(destination)
    finally:
        os.close(destination)


def _rename_noreplace(parent_fd, source, destination):
    """Linux renameat2(RENAME_NOREPLACE), not check-then-rename or replace."""
    if sys.platform != 'linux':
        raise _error('unsupported_atomic_publish')
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, 'renameat2', None)
    if rename is None:
        raise _error('unsupported_atomic_publish')
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(parent_fd, os.fsencode(source), parent_fd, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise _error('collision')
        if code in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.EXDEV):
            raise _error('unsupported_atomic_publish')
        raise _error('atomic_publish_failed')


@contextmanager
def _staging(output):
    root_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parent_fd = stage_fd = None
    stage_name = '.stage-' + uuid.uuid4().hex
    try:
        try:
            os.mkdir(PACK_DIRECTORY, mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        parent_fd = os.open(PACK_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        info = os.fstat(parent_fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise _error('unsafe_staging_directory')
        os.mkdir(stage_name, mode=0o700, dir_fd=parent_fd)
        stage_fd = os.open(stage_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        # Pin the parent directory across all copy, validation and rename work.
        # /proc is Linux-local and is never returned in a manifest or descriptor.
        stage_path = Path(f'/proc/self/fd/{parent_fd}') / stage_name
        yield parent_fd, stage_fd, stage_name, stage_path
    finally:
        if stage_fd is not None:
            os.close(stage_fd)
            # Rename removes this name on success. Never delete a final name.
            try:
                shutil.rmtree(Path(f'/proc/self/fd/{parent_fd}') / stage_name)
            except FileNotFoundError:
                pass
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def restage(video, mctx, conditioning, family_name):
    with safe_errors():
        if not isinstance(family_name, str) or not _FAMILY.fullmatch(family_name):
            raise _error('unsafe_family_name')
        input_root, output = roots()
        # The SDK hands back absolute paths to the assets it just uploaded. Refusing
        # them on shape alone made the node reject its own inputs; _relative still
        # refuses anything that is not strictly under the ComfyUI input root.
        with _sources(input_root, (video, mctx, conditioning), True) as (_, files, family, hashes, check):
            with _staging(output) as (parent_fd, stage_fd, stage_name, stage_path):
                for fd, name in zip(files, NAMES):
                    _copy_file(fd, stage_fd, name)
                check()
                copied = validate_h3_artifact_set(*NAMES, root=stage_path, expected_sha256=hashes)
                if copied != family:
                    raise _error('family_changed')
                os.fsync(stage_fd)
                check()
                _rename_noreplace(parent_fd, stage_name, family_name)
                os.fsync(parent_fd)
            relative = [f'{PACK_DIRECTORY}/{family_name}/{name}' for name in NAMES]
            return _result(relative, copied, relative[0])
