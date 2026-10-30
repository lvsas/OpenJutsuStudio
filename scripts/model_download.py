"""Non-clobbering, explicit model downloads (POSIX; standard library only)."""
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import struct
import unicodedata
import urllib.parse
import urllib.request
import uuid

ERROR = 'Installation failed; existing files preserved. Inspect retained .part files if present.'
CHUNK = 1024 * 1024
BITS = {'BOOL':8, 'U8':8, 'I8':8, 'U16':16, 'I16':16, 'F16':16, 'BF16':16,
        'U32':32, 'I32':32, 'F32':32, 'U64':64, 'I64':64, 'F64':64,
        'F8_E4M3':8, 'F8_E5M2':8, 'F8_E8M0':8, 'F8_E4M3FN':8, 'F4':4}


def relative_name(value):
    if (not isinstance(value, str) or not value or len(value) > 1024
            or '\\' in value or ':' in value or value.startswith('/')
            or any(unicodedata.category(c).startswith('C') for c in value)
            or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError(ERROR)
    return value


def checked_url(url, redirect=False):
    if not isinstance(url, str) or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise ValueError(ERROR)
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ''
    signed_cdn = host.endswith(('.hf.co', '.huggingface.co')) or host == 'huggingface.co'
    if (parsed.scheme != 'https' or not host or parsed.username is not None
            or parsed.password is not None or parsed.fragment
            or (parsed.query and not (redirect and signed_cdn))):
        raise ValueError(ERROR)
    return url


def source_contract(source):
    if not isinstance(source, dict) or not isinstance(source.get('revision'), str) or not source['revision']:
        raise ValueError(ERROR)
    checked_url(source.get('url'))
    size = source.get('size_bytes')
    sha = source.get('sha256')
    if size is not None and (type(size) is not int or size <= 8):
        raise ValueError(ERROR)
    if sha is not None and (not isinstance(sha, str) or re.fullmatch('[0-9a-f]{64}', sha) is None):
        raise ValueError(ERROR)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl, redirect=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(ERROR)
        result[key] = value
    return result


def validate_file(stream, source):
    """Validate exact Safetensors layout, optional upstream size and SHA-256."""
    stream.seek(0, 2)
    size = stream.tell()
    if size <= 8 or (source.get('size_bytes') is not None and size != source['size_bytes']):
        raise ValueError(ERROR)
    stream.seek(0)
    header_size = struct.unpack('<Q', stream.read(8))[0]
    if not 2 <= header_size <= min(32 * CHUNK, size - 8):
        raise ValueError(ERROR)
    header = json.loads(stream.read(header_size), object_pairs_hook=unique_object)
    if not isinstance(header, dict):
        raise ValueError(ERROR)
    ranges = []
    for name, tensor in header.items():
        if name == '__metadata__':
            if not isinstance(tensor, dict) or any(not isinstance(v, str) for v in tensor.values()):
                raise ValueError(ERROR)
            continue
        if not isinstance(tensor, dict):
            raise ValueError(ERROR)
        shape, offsets, dtype = tensor.get('shape'), tensor.get('data_offsets'), tensor.get('dtype')
        if (not isinstance(shape, list) or any(type(n) is not int or n < 0 for n in shape)
                or not isinstance(offsets, list) or len(offsets) != 2
                or any(type(n) is not int or n < 0 for n in offsets)
                or not isinstance(dtype, str) or dtype not in BITS):
            raise ValueError(ERROR)
        start, end = offsets
        if start > end or end - start != (math.prod(shape) * BITS[dtype] + 7) // 8:
            raise ValueError(ERROR)
        ranges.append((start, end))
    cursor = 0
    for start, end in sorted(ranges):
        if start != cursor:
            raise ValueError(ERROR)
        cursor = end
    if not ranges or cursor != size - 8 - header_size:
        raise ValueError(ERROR)
    if source.get('sha256'):
        stream.seek(0)
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != source['sha256']:
            raise ValueError(ERROR)


def parent_fd(comfyui, relative):
    """Walk pinned directory descriptors, refusing symlinks at every component."""
    root = Path(os.path.abspath(comfyui))
    parts = (root / 'models').parts
    fd = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        for part in Path(relative).parts[:-1]:
            try:
                os.mkdir(part, mode=0o755, dir_fd=fd)
            except FileExistsError:
                pass
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def fetch(item, comfyui, opener=None):
    """Install one validated new file, retaining staging; never delete/overwrite."""
    directory = None
    try:
        relative = relative_name(item['relative'])
        source = item['download']
        source_contract(source)
        directory = parent_fd(comfyui, relative)
        name = Path(relative).name
        try:
            existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            with os.fdopen(existing, 'rb') as stream:
                validate_file(stream, source)
            return 'skip (existing file verified)'
        expected = source.get('size_bytes')
        disk = os.fstatvfs(directory)
        if expected and disk.f_bavail * disk.f_frsize < expected:
            raise ValueError(ERROR)
        stage = name + '.' + uuid.uuid4().hex + '.part'
        stage_fd = os.open(stage, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        if source.get('gated') and not os.environ.get('HF_TOKEN'):
            return 'skip (gated: export HF_TOKEN and accept the model terms)'
        headers = {'User-Agent': 'OpenGenjutsu-model-installer'}
        if os.environ.get('HF_TOKEN'):
            headers['Authorization'] = 'Bearer ' + os.environ['HF_TOKEN']
        request = urllib.request.Request(source['url'], headers=headers)
        open_url = opener or urllib.request.build_opener(SafeRedirect()).open
        with os.fdopen(stage_fd, 'w+b') as stream:
            with open_url(request, timeout=60) as response:
                length = response.headers.get('Content-Length')
                length = int(length) if length is not None else None
                if length is not None and (length < 0 or (expected is not None and length != expected)):
                    raise ValueError(ERROR)
                total = 0
                while data := response.read(CHUNK):
                    total += len(data)
                    if total > (expected if expected is not None else length if length is not None else 1024 ** 4):
                        raise ValueError(ERROR)
                    stream.write(data)
                if length is not None and total != length:
                    raise ValueError(ERROR)
            stream.flush()
            os.fsync(stream.fileno())
            validate_file(stream, source)
        os.link(stage, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        os.fsync(directory)
        return 'installed (verified; .part hardlink retained without duplicate storage)'
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError, http.client.HTTPException):
        raise ValueError(ERROR) from None
    finally:
        if directory is not None:
            os.close(directory)
