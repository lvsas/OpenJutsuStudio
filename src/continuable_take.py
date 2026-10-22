"""Immutable native H3 Takes, independent of editing placements and app config.

Import is an operator boundary: explicit local files, a trusted stable source
root and a caller-owned WORK. No SDK, torch, network, or import-time IO. Private
capture evidence is never returned by the public metadata APIs. An executed
external graph is evidence, NOT an approved application render recipe.

Integrity is SHA-256 content integrity, not authenticated provenance. Read-only
permissions prevent accidental edits, not edits by the owner/root. Before any
serving/SDK use call get_validated_family; list/get inspect frozen metadata only.
Path checks reject symlinks, traversal and special files; like the existing pure
validator, this is not a sandbox against hostile concurrent ancestor replacement.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Sequence
import subprocess
import tempfile
import uuid

from safetensor_header import HeaderValidationError, decode_json_bytes, read_safetensors_header
from timeline_artifacts import H3ArtifactSet, validate_h3_artifact_set

_ID = re.compile(r'[0-9a-f]{32}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
# References live beside the family, never inside its three-file contract.
_REFERENCE_NAME = re.compile(r'reference-[1-9][0-9]{0,2}\.(png|jpg|jpeg|webp)\Z')
_REFERENCE_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.webp'})
_REFERENCE_MAX_BYTES = 32 * 1024 * 1024


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()
_TOKEN = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_NUMBER = re.compile(r'-?[0-9]{1,12}(?:\.[0-9]{1,12}|/[0-9]{1,12})?\Z')
_NAMES = {'video': 'take.mp4', 'mctx': 'take.mctx.safetensors',
          'conditioning': 'take.cond.safetensors'}
_MAX_JSON = 16 * 1024 * 1024
_FORMAT = 'opengenjutsu-continuable-take'
_META_NUMBERS = ('parent_join_frame', 'pinned_head_frames', 'pinned_tail_frames',
                 'overlap_frames', 'overlap_tail_frames', 'audio_synced', 'audio_phase')
_PIN_KEYS = frozenset(('source_id', 'source_kind', 'source_start', 'source_frames',
                       'place', 'audio_window', 'mode', 'handover_edge',
                       'audio_start_step', 'audio_steps'))


def _canonical(value) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError('Evidence must be finite JSON data') from exc


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _take_id(value) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('Take identifier must be exactly 32 lowercase hexadecimal characters')
    return value


class _DirectoryPublicationUncertain(OSError):
    """The rename succeeded; a later directory-sync acknowledgement failed."""


class TakePublicationUncertain(OSError):
    """Public recovery handle; never retry an anonymous import blindly."""

    def __init__(self, take_id: str, phase: str):
        self.take_id = _take_id(take_id)
        if phase not in ('directory_sync', 'readback'):
            raise ValueError('Invalid publication confirmation phase')
        self.phase = phase
        super().__init__('Take publication is visible; confirmation is incomplete')


def _token(value):
    if value is not None and (not isinstance(value, str) or not _TOKEN.fullmatch(value)):
        raise ValueError('Origin must be a plain identifier or label, not a path or URL')
    return value


def _absolute(path) -> Path:
    path = Path(path)
    if '..' in path.parts:
        raise ValueError('Path traversal is not allowed')
    return path.absolute()


def _directory(path: Path, *, create=False) -> Path:
    """Walk directories with NOFOLLOW, including all ancestors."""
    path = _absolute(path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                else:
                    # Persist each newly created ancestor entry, not just its leaf.
                    os.fsync(fd)
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    finally:
        os.close(fd)
    return path


def _open_file(path: Path):
    _directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError('Artifact must be a regular file')
    return os.fdopen(fd, 'rb')


def _source(path, root: Path) -> Path:
    candidate = Path(path)
    candidate = _absolute(candidate if candidate.is_absolute() else root / candidate)
    if not candidate.is_relative_to(root) or candidate == root:
        raise ValueError('Artifact is outside the explicit source root')
    with _open_file(candidate):
        pass
    return candidate


def _read_json(path: Path):
    with _open_file(path) as stream:
        raw = stream.read(_MAX_JSON + 1)
    if len(raw) > _MAX_JSON:
        raise ValueError('Capture or capsule exceeds the JSON byte limit')
    return decode_json_bytes(raw)


def _write_json(path: Path, value):
    raw = _canonical(value)
    if len(raw) > _MAX_JSON:
        raise ValueError('Capture or capsule exceeds the JSON byte limit')
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _copy_file(source: Path, destination: Path, expected: str):
    digest = hashlib.sha256()
    with _open_file(source) as src, destination.open('xb') as dst:
        for block in iter(lambda: src.read(1024 * 1024), b''):
            digest.update(block)
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())
    if digest.hexdigest() != expected:
        raise ValueError('Source artifact changed during private copy')


def _publish_directory(staging: Path, destination: Path):
    """Sync a flat sealed family, publish no-replace, then sync its parent.

    A final parent-sync failure is reported but the now-visible destination is
    never removed. Callers must re-read its known ID before attempting recovery.
    These are explicit Linux fsync boundaries, not a power-cut test/guarantee.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, 'renameat2', None)
    if os.name != 'posix' or renameat2 is None:
        raise RuntimeError('Take publication requires Linux renameat2 no-replace')
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    for path in staging.iterdir():
        with _open_file(path) as stream:
            os.fsync(stream.fileno())  # Includes final file permissions after sealing.
    stage_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(stage_fd)
    finally:
        os.close(stage_fd)
    if renameat2(-100, os.fsencode(staging), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError('Take identifier is already published')
        raise OSError(error, 'Atomic Take publication failed')
    try:
        parent_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except OSError as exc:
        # Distinguish post-rename uncertainty from failures before publication.
        raise _DirectoryPublicationUncertain('Publication visible; durability unconfirmed') from exc


def _safe_atom(value):
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else None


def _pin(value):
    if not isinstance(value, dict):
        raise ValueError('Native pins must be JSON objects')
    # The full lossless metadata is private. Public pins exclude paths, URLs,
    # arbitrary extension fields and arbitrary free text.
    return {key: item for key, item in value.items() if key in _PIN_KEYS and (
        isinstance(item, str) and _TOKEN.fullmatch(item)
        or type(item) in (int, bool)
        or type(item) is float and math.isfinite(item))}


def _lineage(meta):
    parent = meta.get('parent_id')
    pins = decode_json_bytes(meta['pins'].encode()) if 'pins' in meta else None
    if pins is not None and (not isinstance(pins, list) or len(pins) > 4096):
        raise ValueError('Native pins must be a bounded JSON array')
    value = {'self_id': meta.get('self_id'),
             'parent_id': parent if isinstance(parent, str) and _SHA.fullmatch(parent) else None,
             'relation': _safe_atom(meta.get('relation')),
             'parent_grade': _safe_atom(meta.get('parent_grade')),
             'pins': [_pin(pin) for pin in pins] if pins is not None else None}
    for key in _META_NUMBERS:
        text = meta.get(key)
        value[key] = text if isinstance(text, str) and _NUMBER.fullmatch(text) else None
    return value


def _recipe(graph, completeness, source):
    if completeness not in ('unknown', 'partial', 'complete'):
        raise ValueError('Graph completeness must be unknown, partial or complete')
    if source not in ('operator_capture', 'mp4_prompt'):
        raise ValueError('Graph source must be explicit operator capture or embedded MP4 prompt')
    if graph is None:
        if completeness != 'unknown':
            raise ValueError('An absent graph cannot have known completeness')
    elif not (isinstance(graph, dict) and graph or isinstance(graph, str)
              and graph.strip().startswith('{') and graph.strip().endswith('}')):
        raise ValueError('Capture must be a nonempty graph object, opaque object text, or absent')
    # A non-finite ComfyUI execution graph is kept opaque/private, but its
    # canonical execution-graph digest still hashes the actual parsed graph,
    # with the explicitly named Python/ComfyUI non-finite JSON convention.
    graph_hash = None
    if graph is not None:
        if isinstance(graph, str):
            _decode_graph_capture(graph.encode('utf-8'))  # syntax/duplicate-key guard
            raw = json.dumps(json.loads(graph), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True, allow_nan=True).encode('utf-8')
            graph_hash = hashlib.sha256(raw).hexdigest()
        else:
            graph_hash = _digest(graph)
    return {'availability': 'captured_execution_graph' if graph is not None else 'unavailable',
            'graph_sha256': graph_hash,
            'graph_encoding': ('opaque_text' if isinstance(graph, str) else 'json_object')
                              if graph is not None else None,
            'graph_canonicalization': ('python-json-sort-keys-ascii-nonfinite-v1'
                if isinstance(graph, str) else 'json-sort-keys-ascii-v1') if graph is not None else None,
            'source': source if graph is not None else None,
            'completeness': completeness, 'render_recipe': 'unknown',
            'seeds': 'unknown', 'model_identities': 'unknown',
            'app_replay': 'unreviewed' if graph is not None else 'unavailable'}


def _decode_graph_capture(raw: bytes) -> dict | str:
    """Keep unsupported execution JSON (e.g. Infinity) as exact opaque text.

    Do not turn Infinity into a guessed finite parameter or silently drop a node.
    The private-evidence hash covers the exact text. graph_sha256 uses the
    explicitly named canonical Python/ComfyUI execution-JSON convention.
    Opaque capture does not prove application replayability.
    """
    try:
        graph = decode_json_bytes(raw)
    except HeaderValidationError:
        text = raw.decode('utf-8')
        def unique(pairs):
            result = dict(pairs)
            if len(result) != len(pairs):
                raise ValueError('Duplicate captured graph object key')
            return result
        # Python/ComfyUI permit non-finite literals. Check full syntax without
        # duplicate-key loss, then DISCARD this parse and retain exact text.
        opaque = json.loads(text, object_pairs_hook=unique)
        if not isinstance(opaque, dict) or not opaque:
            raise ValueError('Opaque capture is not a complete graph object')
        return text
    if not isinstance(graph, dict) or not graph:
        raise ValueError('Captured prompt must be a nonempty graph object')
    return graph


def read_embedded_prompt(video: str | Path) -> dict | str:
    """Capture actual local MP4 prompt, retaining unsupported JSON as opaque text."""
    path = _absolute(video)
    with _open_file(path):
        pass
    run = subprocess.run([
        'ffprobe', '-v', 'error', '-protocol_whitelist', 'file', '-f', 'mov',
        '-enable_drefs', '0', '-use_absolute_path', '0', '-show_entries',
        'format_tags=prompt', '-of', 'json', str(path)], capture_output=True, check=True, timeout=30)
    if len(run.stdout) > _MAX_JSON:
        raise ValueError('Embedded prompt exceeds the JSON byte limit')
    data = decode_json_bytes(run.stdout)
    text = data.get('format', {}).get('tags', {}).get('prompt')
    if not isinstance(text, str):
        raise ValueError('MP4 has no captured prompt tag; provide explicit operator capture')
    return _decode_graph_capture(text.encode('utf-8'))


def read_captured_graph(path: str | Path) -> dict | str:
    """Operator-only bounded, regular-file JSON input; never a public path API."""
    with _open_file(_absolute(path)) as stream:
        raw = stream.read(_MAX_JSON + 1)
    if len(raw) > _MAX_JSON:
        raise ValueError('Graph capture exceeds the JSON byte limit')
    return _decode_graph_capture(raw)


@dataclass(frozen=True, slots=True)
class TakeRecord:
    """Native Take identity and frozen public capsule, not a timeline placement."""
    take_id: str
    capsule_sha256: str
    _json: bytes

    @property
    def engine(self):
        return 'H3OBVPM'

    def to_manifest(self) -> dict:
        """Fresh path-free public data; deliberately never claims current file integrity."""
        return {**decode_json_bytes(self._json), 'integrity': 'frozen_metadata_only'}


@dataclass(frozen=True, slots=True)
class ValidatedTakeFamily:
    """Local-use result, NOT a public response: file paths for a future SDK adapter.

    Validation covers this call only. Consumers must use immediately on the same
    trusted host; it is not a lease against owner/root writes after validation.
    """
    record: TakeRecord
    video: Path
    mctx: Path
    conditioning: Path
    artifacts: H3ArtifactSet


def _capsule(take_id, family, meta, recipe, origin, evidence, identity=None):
    body = {'format': _FORMAT, 'schema_version': 1, 'take_id': take_id,
            'engine': 'H3OBVPM', 'engine_contract_version': 1,
            'family': family, 'lineage': _lineage(meta), 'recipe': recipe,
            'origin': origin, 'private_evidence_sha256': _digest(evidence),
            'runtime_compatibility': 'unproven'}
    if identity is not None:
        body['identity'] = identity
    return {**body, 'capsule_sha256': _digest(body)}


def _validate_capsule(value, take_id):
    """Validate public vocabulary as well as its checksum; never echo free-form JSON."""
    required = {'format', 'schema_version', 'take_id', 'engine', 'engine_contract_version',
                'family', 'lineage', 'recipe', 'origin', 'private_evidence_sha256',
                'runtime_compatibility', 'capsule_sha256'}
    # ``identity`` is optional so every capsule written before it existed stays valid.
    if (not isinstance(value, dict) or not set(value) <= required | {'identity'}
            or set(value) - {'identity'} != required):
        raise ValueError('Unsupported Take capsule shape')
    if 'identity' in value:
        identity = value['identity']
        if not isinstance(identity, dict) or set(identity) != {'references'}:
            raise ValueError('Unsupported Take identity shape')
        references = identity['references']
        if not isinstance(references, list) or not references:
            raise ValueError('A take identity needs at least one reference')
        for item in references:
            if not isinstance(item, dict) or set(item) != {'filename', 'sha256'}:
                raise ValueError('Unsupported reference entry')
            name, digest = item['filename'], item['sha256']
            if not isinstance(name, str) or not _REFERENCE_NAME.fullmatch(name):
                raise ValueError('Invalid reference filename')
            if not isinstance(digest, str) or not _SHA.fullmatch(digest):
                raise ValueError('Invalid reference digest')
    if (value['format'] != _FORMAT or type(value['schema_version']) is not int
            or value['schema_version'] != 1 or value['take_id'] != take_id
            or value['engine'] != 'H3OBVPM' or type(value['engine_contract_version']) is not int
            or value['engine_contract_version'] != 1 or value['runtime_compatibility'] != 'unproven'):
        raise ValueError('Unsupported Take capsule identity or version')
    for key in ('private_evidence_sha256', 'capsule_sha256'):
        if not isinstance(value[key], str) or not _SHA.fullmatch(value[key]):
            raise ValueError('Invalid capsule digest')
    if _digest({k: v for k, v in value.items() if k != 'capsule_sha256'}) != value['capsule_sha256']:
        raise ValueError('Take capsule integrity mismatch')
    origin = value['origin']
    if not isinstance(origin, dict) or set(origin) != {'source_job', 'operator_label'}:
        raise ValueError('Invalid frozen origin')
    for token in origin.values():
        _token(token)
    recipe = value['recipe']
    if not isinstance(recipe, dict):
        raise ValueError('Invalid frozen recipe evidence')
    present = recipe.get('availability') == 'captured_execution_graph'
    placeholder = '{"opaque":true}' if recipe.get('graph_encoding') == 'opaque_text' else {'placeholder': True}
    expected_recipe = _recipe(placeholder if present else None,
                              recipe.get('completeness'), recipe.get('source') or 'operator_capture')
    if present:
        digest = recipe.get('graph_sha256')
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ValueError('Invalid graph digest')
        expected_recipe['graph_sha256'] = digest
    if recipe != expected_recipe:
        raise ValueError('Unsupported frozen recipe evidence')
    lineage = value['lineage']
    if not isinstance(lineage, dict) or set(lineage) != {
            'self_id', 'parent_id', 'relation', 'parent_grade', 'pins', *_META_NUMBERS}:
        raise ValueError('Invalid frozen lineage')
    # Round-trip through the same public allowlist used at import.
    meta = {k: v for k, v in lineage.items() if k != 'pins' and v is not None}
    if lineage['pins'] is not None:
        meta['pins'] = _canonical(lineage['pins']).decode()
    if _lineage(meta) != lineage:
        raise ValueError('Unsafe frozen lineage')
    family = value['family']
    if not isinstance(family, dict) or set(family) != {
            'format', 'schema_version', 'assets', 'context', 'conditioning', 'verification'}:
        raise ValueError('Invalid frozen family')
    if (family['format'] != 'opengenjutsu-h3-artifact-set' or family['schema_version'] != 1
            or family['conditioning'] != {'format': 'obvpm_cond_v1'}
            or family['verification'] != {'scope': 'file-integrity-and-media-geometry',
                'model_runtime_compatibility': False, 'conditioning_tensor_values': False}):
        raise ValueError('Unsupported frozen family')
    assets = family['assets']
    if not isinstance(assets, dict) or set(assets) != set(_NAMES):
        raise ValueError('Incomplete frozen family')
    for role, asset in assets.items():
        if (not isinstance(asset, dict) or set(asset) != {'sha256', 'size_bytes', 'suffix'}
                or not isinstance(asset['sha256'], str) or not _SHA.fullmatch(asset['sha256'])
                or type(asset['size_bytes']) is not int or asset['size_bytes'] <= 0
                or asset['suffix'] != _NAMES[role][4:]):
            raise ValueError('Invalid frozen artifact')
    context = family['context']
    if (not isinstance(context, dict) or set(context) != {
            'format', 'self_id', 'width', 'height', 'fps', 'raw_frames', 'delivered_frames'}
            or context['format'] != 'mctx_v1' or context['self_id'] != assets['video']['sha256']
            or lineage['self_id'] != context['self_id']
            or any(type(context[k]) is not int or context[k] <= 0 for k in (
                'width', 'height', 'raw_frames', 'delivered_frames'))
            or type(context['fps']) not in (int, float) or not math.isfinite(context['fps'])
            or not 0 < context['fps'] <= 1000
            or context['delivered_frames'] > context['raw_frames']):
        raise ValueError('Invalid frozen context')


def _store(work, *, create=False):
    return _directory(_absolute(work) / 'timeline' / 'continuable-takes', create=create)


def get_take(work: str | Path, take_id: str) -> TakeRecord:
    """Read only the bounded capsule; artifacts have NOT been freshly rehashed."""
    take_id = _take_id(take_id)
    folder = _directory(_store(work) / take_id)
    value = _read_json(folder / 'capsule.json')
    _validate_capsule(value, take_id)
    return TakeRecord(take_id, value['capsule_sha256'], _canonical(value))


def list_takes(work: str | Path) -> tuple[TakeRecord, ...]:
    """Sorted frozen metadata only. Corrupt ID-scoped entries fail closed."""
    try:
        store = _store(work)
    except FileNotFoundError:
        return ()
    ids = sorted(path.name for path in store.iterdir() if _ID.fullmatch(path.name))
    return tuple(get_take(work, take_id) for take_id in ids)


def get_validated_family(work: str | Path, take_id: str) -> ValidatedTakeFamily:
    """Mandatory before serving/use: revalidate capsule, private evidence and all bytes."""
    record = get_take(work, take_id)
    value = decode_json_bytes(record._json)
    folder = _directory(_store(work) / record.take_id)
    evidence = _read_json(folder / 'capture.private.json')
    if not isinstance(evidence, dict) or set(evidence) != {'captured_graph', 'mctx_metadata'}:
        raise ValueError('Unsupported private capture evidence')
    if _digest(evidence) != value['private_evidence_sha256']:
        raise ValueError('Private capture integrity mismatch')
    paths = {role: _source(folder / name, folder) for role, name in _NAMES.items()}
    artifacts = validate_h3_artifact_set(paths['video'], paths['mctx'], paths['conditioning'], root=folder,
        expected_sha256={role: asset['sha256'] for role, asset in value['family']['assets'].items()})
    with _open_file(paths['mctx']) as stream:
        meta = dict(read_safetensors_header(stream).metadata)
    recipe = _recipe(evidence['captured_graph'], value['recipe']['completeness'],
                     value['recipe']['source'] or 'operator_capture')
    # The capsule is sealed with its identity block, so revalidation must rebuild
    # it with the same block. Omitting it made every take that carries a reference
    # fail against its own record.
    if (meta != evidence['mctx_metadata'] or _capsule(record.take_id, artifacts.to_manifest(),
            meta, recipe, value['origin'], evidence,
            identity=value.get('identity')) != value):
        raise ValueError('Frozen Take evidence differs from validated family')
    if get_take(work, record.take_id) != record:
        raise ValueError('Capsule changed during validation')
    return ValidatedTakeFamily(record, **paths, artifacts=artifacts)


def import_family(video: str | Path, mctx: str | Path, conditioning: str | Path, *,
                  root: str | Path, work: str | Path, captured_graph: dict | str | None,
                  take_id: str | None = None, graph_completeness: str = 'unknown',
                  graph_source: str = 'operator_capture', source_job: str | None = None,
                  operator_label: str | None = None,
                  references: Sequence[str | Path] = ()) -> TakeRecord:
    """Validate, privately stream-copy, revalidate, seal and atomically publish.

    ``captured_graph`` is actual execution evidence, not a current DB workflow.
    None explicitly records its absence. Completeness is unknown unless the
    operator attests otherwise. Even complete external graphs stay unreviewed.
    Unsupported/non-finite execution JSON can be retained as exact opaque object
    text; graph_encoding and graph_canonicalization describe its digest contract.
    ``mp4_prompt`` additionally checks equality with the actual embedded tag.
    Omitting take_id generates a strict UUID-hex ID; explicit None is equivalent.
    """
    take_id = _take_id(uuid.uuid4().hex if take_id is None else take_id)
    origin = {'source_job': _token(source_job), 'operator_label': _token(operator_label)}
    # Copy caller-owned JSON so mutations cannot alter frozen evidence.
    graph = decode_json_bytes(_canonical(captured_graph))
    recipe = _recipe(graph, graph_completeness, graph_source)
    root = _directory(_absolute(root))
    paths = {role: _source(path, root) for role, path in (
        ('video', video), ('mctx', mctx), ('conditioning', conditioning))}
    inspected = validate_h3_artifact_set(paths['video'], paths['mctx'], paths['conditioning'], root=root)
    hashes = {asset.role: asset.sha256 for asset in inspected.assets}
    # References are the identity of the take, not part of the family triplet.
    # They are copied inside the take so a continuation never has to guess them.
    reference_sources = [_source(path, root) for path in references]
    reference_assets = []
    for index, source in enumerate(reference_sources, start=1):
        if source.suffix.lower() not in _REFERENCE_SUFFIXES:
            raise ValueError('A reference must be a PNG, JPEG or WebP image')
        if source.stat().st_size > _REFERENCE_MAX_BYTES:
            raise ValueError('A reference image is larger than the accepted limit')
        reference_assets.append((f'reference-{index}{source.suffix.lower()}', source,
                                 _file_sha256(source)))
    with _open_file(paths['mctx']) as stream:
        meta = dict(read_safetensors_header(stream).metadata)
    if graph_source == 'mp4_prompt' and (graph is None or _digest(read_embedded_prompt(paths['video'])) != _digest(graph)):
        raise ValueError('Captured graph differs from actual embedded MP4 prompt')
    evidence = {'captured_graph': graph, 'mctx_metadata': meta}
    identity = ({'references': [{'filename': name, 'sha256': digest}
                                for name, _source_path, digest in reference_assets]}
                if reference_assets else None)
    capsule = _capsule(take_id, inspected.to_manifest(), meta, recipe, origin, evidence,
                       identity=identity)
    _validate_capsule(capsule, take_id)
    store = _store(work, create=True)
    destination = store / take_id
    if os.path.lexists(destination):
        raise FileExistsError('Take identifier is already published')
    staging = Path(tempfile.mkdtemp(prefix='.' + take_id + '.', suffix='.part', dir=store))
    published = False
    try:
        copied = {role: staging / _NAMES[role] for role in paths}
        for role, source in paths.items():
            _copy_file(source, copied[role], hashes[role])
        if validate_h3_artifact_set(**copied, root=staging, expected_sha256=hashes) != inspected:
            raise ValueError('Private family copy differs from source inspection')
        with _open_file(copied['mctx']) as stream:
            if dict(read_safetensors_header(stream).metadata) != meta:
                raise ValueError('Native metadata changed between inspection and private copy')
        if validate_h3_artifact_set(**paths, root=root, expected_sha256=hashes) != inspected:
            raise ValueError('Source family changed during import')
        for name, source, digest in reference_assets:
            _copy_file(source, staging / name, digest)
            if _file_sha256(staging / name) != digest:
                raise ValueError('Private reference copy differs from its source')
        _write_json(staging / 'capture.private.json', evidence)
        _write_json(staging / 'capsule.json', capsule)
        for path in staging.iterdir():
            path.chmod(0o400)
        staging.chmod(0o500)
        try:
            _publish_directory(staging, destination)
        except _DirectoryPublicationUncertain as exc:
            published = True  # Rename succeeded even though directory sync did not.
            raise TakePublicationUncertain(take_id, 'directory_sync') from exc
        else:
            published = True
    finally:
        # Never let a lookup of the renamed-away staging path mask recovery.
        if not published and staging.exists():
            staging.chmod(0o700)
            shutil.rmtree(staging)
    # Read back the exact published target; no mutable catalog/placement is made.
    try:
        return get_take(work, take_id)
    except (OSError, ValueError) as exc:
        raise TakePublicationUncertain(take_id, 'readback') from exc
