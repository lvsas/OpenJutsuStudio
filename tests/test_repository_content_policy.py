"""What ships must not name an adapter the product does not ship.

The contest repository is intended for public review. A workflow that merely *mentions* a style LoRA
is a rule problem even when the switch is off and the file is never loaded: the
graph is read by people, and an NSFW adapter name in a shipped graph is
disqualifying. This guard is repository-wide so the mention cannot come back
through a re-export, a doc or a fixture. Distributed ZIP/TAR members are checked
without extraction. This checks the current tree, not Git history or the safety
of remote model weights.
"""
import bz2
import gzip
import io
import json
import lzma
import os
import re
import stat
import tarfile
import tempfile
from pathlib import Path
import unittest
from unittest import mock
import zipfile
from release_inventory import release_files

ROOT = Path(__file__).resolve().parents[1]

# Every LoRA a shipped graph may name. Adding one is a product decision: it is
# installed on the target, audited for the contest and listed in dependencies.json.
ALLOWED_LORAS = {
    'H3/h3_character_swap_v1.5.safetensors',                        # Swap identity
    'minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors',  # H3 speed
    'LTX25_Ripple_v11.safetensors',                                 # LTX identity
}
SKIP_DIRS = {'.git', '.venv', 'work', 'cache', 'node_modules', '__pycache__'}
TEXT_SUFFIXES = {'.py', '.js', '.mjs', '.json', '.md', '.html', '.css',
                 '.yaml', '.yml', '.sh', '.txt'}
ARCHIVE_SUFFIXES = ('.zip', '.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2',
                    '.tar.xz', '.txz')
# Explicit resource limits: an uninspectable artifact fails rather than passes.
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2048
MAX_ARCHIVE_DEPTH = 3
# Family names of adult adapters that must never appear in a submitted file.
# Written in fragments so this guard does not match its own source and cannot be
# satisfied by editing one literal. Both spellings are independently forbidden.
_FAMILIES = ('mys' 'tic', 'mys' 'tique', 'foot' 'job', 'sex' 'god', 'deep' 'throat',
             'hm' 'pussy', 'vag' 'assist', 'nsfw[_ -]?anime')
FORBIDDEN_ADAPTERS = re.compile('|'.join(_FAMILIES), re.I)


def _is_archive(name):
    return str(name).lower().endswith(ARCHIVE_SUFFIXES)


def _shipped_files():
    yield from release_files(ROOT)


def _bounded_read(stream, limit):
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('content exceeds inspection limit')
    return data


def _scan_payload(name, data, budget, depth=0):
    if _is_archive(name):
        yield from _scan_archive(name, data, budget, depth + 1)
    elif Path(name).suffix.lower() in TEXT_SUFFIXES:
        encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        text = data.decode(encoding, errors='replace')
        if FORBIDDEN_ADAPTERS.search(text):
            yield name
        elif Path(name).suffix.lower() == '.json':
            # Include escaped JSON strings, keys, metadata and disabled nodes.
            try:
                decoded = json.dumps(json.loads(text), ensure_ascii=False)
            except ValueError:
                decoded = text
            if FORBIDDEN_ADAPTERS.search(decoded):
                yield name


def _scan_archive(name, data, budget, depth):
    if depth > MAX_ARCHIVE_DEPTH:
        raise ValueError('archive nesting exceeds inspection limit')

    def inspect(member_name, size, opener):
        budget[0] += 1
        budget[1] += size
        if (budget[0] > MAX_ARCHIVE_MEMBERS or size > MAX_MEMBER_BYTES or
                budget[1] > MAX_EXPANDED_BYTES or size < 0):
            raise ValueError('archive exceeds inspection limits')
        label = f'{name}!{member_name}'
        # Do not apply workspace exclusions to members of distributed archives.
        if opener is not None and (_is_archive(member_name) or
                                   Path(member_name).suffix.lower() in TEXT_SUFFIXES):
            with opener() as stream:
                payload = _bounded_read(stream, MAX_MEMBER_BYTES)
            yield from _scan_payload(label, payload, budget, depth)

    if name.lower().endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError('archive links cannot be inspected')
                opener = None if member.is_dir() else lambda member=member: archive.open(member)
                yield from inspect(member.filename, member.file_size, opener)
    else:
        # Bound decompression before TAR parses extended headers as well as files.
        for magic, reader in ((b'\x1f\x8b', gzip.open),
                              (b'BZh', bz2.BZ2File),
                              (b'\xfd7zXZ\x00', lzma.LZMAFile)):
            if data.startswith(magic):
                with reader(io.BytesIO(data), mode='rb') as stream:
                    data = _bounded_read(stream, MAX_EXPANDED_BYTES)
                break
        # Stream the headers rather than building an unbounded getmembers list.
        with tarfile.open(fileobj=io.BytesIO(data), mode='r|') as archive:
            for member in archive:
                if not (member.isfile() or member.isdir()):
                    raise ValueError('archive special members cannot be inspected')
                opener = None if member.isdir() else lambda member=member: archive.extractfile(member)
                yield from inspect(member.name, member.size, opener)


def _content_policy_offenders():
    offenders = []
    try:
        paths = list(_shipped_files())
    except (OSError, ValueError):
        return ['release inventory unavailable']
    for path in paths:
        label = str(path.relative_to(ROOT))
        try:
            limit = MAX_ARCHIVE_BYTES if _is_archive(label) else MAX_MEMBER_BYTES
            with path.open('rb') as stream:
                data = _bounded_read(stream, limit)
            offenders.extend(_scan_payload(label, data, [0, 0]))
        except (OSError, ValueError, EOFError, RuntimeError, zipfile.BadZipFile,
                NotImplementedError, tarfile.TarError, lzma.LZMAError,
                RecursionError, OverflowError):
            # No content or host-specific exception details in test output.
            offenders.append(f'{label} (unreadable or over inspection limits)')
    return offenders


class ShippedWorkflowPolicyTests(unittest.TestCase):
    def test_shipped_workflows_only_name_audited_adapters(self):
        found = {}
        for path in sorted((ROOT / 'workflows').glob('*.json')):
            graph = json.loads(path.read_text())
            for node_id, node in graph.items():
                if not isinstance(node, dict) or node.get('class_type') != 'LoraLoaderModelOnly':
                    continue
                name = (node.get('inputs') or {}).get('lora_name')
                if isinstance(name, str):
                    found.setdefault(name, []).append(f'{path.name}:{node_id}')
        self.assertEqual({}, {name: where for name, where in found.items()
                              if name not in ALLOWED_LORAS},
                         'A shipped workflow names a LoRA this product does not audit')

    def test_no_shipped_file_names_an_adult_adapter_family(self):
        self.assertEqual([], _content_policy_offenders(),
                         'A submitted file mentions an adapter this product must not ship')


class ContentPolicyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def assert_policy(self, *, rejected):
        # Exercise the actual repository guard, not a separate test-only regex.
        with mock.patch.dict(globals(), ROOT=self.root):
            guard = ShippedWorkflowPolicyTests(
                'test_no_shipped_file_names_an_adult_adapter_family')
            if rejected:
                with self.assertRaises(AssertionError):
                    guard.test_no_shipped_file_names_an_adult_adapter_family()
            else:
                guard.test_no_shipped_file_names_an_adult_adapter_family()

    def test_git_delivery_ignores_untracked_private_docs_but_checks_tracked_sources(self):
        (self.root / '.git').write_text('fixture marker, no real Git operations')
        (self.root / 'docs' / 'plans').mkdir(parents=True)
        (self.root / 'docs' / 'plans' / 'local.md').write_text('mys' + 'tique')
        (self.root / 'src').mkdir()
        source = self.root / 'src' / 'shipped.py'
        source.write_text('safe = True')
        result = mock.Mock(stdout=b'src/shipped.py\0', returncode=0)
        with mock.patch('subprocess.run', return_value=result):
            self.assert_policy(rejected=False)
            source.write_text('mys' + 'tique')
            self.assert_policy(rejected=True)

    def test_untracked_archives_are_still_inspected_in_a_git_delivery(self):
        (self.root / '.git').write_text('fixture marker')
        (self.root / 'docs').mkdir()
        (self.root / 'docs' / 'ignored.zip').write_bytes(b'corrupt archive')
        result = mock.Mock(stdout=b'', returncode=0)
        with mock.patch('subprocess.run', return_value=result):
            self.assert_policy(rejected=True)

    def test_git_inventory_failure_fails_closed(self):
        (self.root / '.git').write_text('fixture marker')
        with mock.patch('subprocess.run', side_effect=OSError('fixture')):
            self.assert_policy(rejected=True)

    def test_second_spelling_in_dormant_json_metadata_is_rejected(self):
        graph = {'42': {'class_type': 'Note', 'inputs': {'enabled': False},
                        '_meta': {'title': 'MYS' + 'TIQUE_adapter.safetensors'}}}
        (self.root / 'workflow.json').write_text(json.dumps(graph))
        self.assert_policy(rejected=True)

    def test_distributed_zip_metadata_is_rejected(self):
        dist = self.root / 'dist'
        dist.mkdir()
        with zipfile.ZipFile(dist / 'workflows.zip', 'w') as archive:
            archive.writestr('graphs/workflow.json', json.dumps(
                {'metadata': {'unused': 'mys' + 'tic_adapter.safetensors'}}))
        self.assert_policy(rejected=True)


    def archive_bytes(self, name, members):
        buffer = io.BytesIO()
        if name.lower().endswith('.zip'):
            with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('graphs.json/', b'')
                for member_name, payload in members:
                    archive.writestr(member_name, payload)
        else:
            mode = ('w:gz' if name.endswith(('.tar.gz', '.tgz')) else
                    'w:bz2' if name.endswith(('.tar.bz2', '.tbz2')) else
                    'w:xz' if name.endswith(('.tar.xz', '.txz')) else 'w')
            with tarfile.open(fileobj=buffer, mode=mode) as archive:
                directory = tarfile.TarInfo('graphs.json')
                directory.type = tarfile.DIRTYPE
                archive.addfile(directory)
                for member_name, payload in members:
                    info = tarfile.TarInfo(member_name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
        return buffer.getvalue()

    def test_both_spellings_are_case_insensitive_in_all_json_fields(self):
        path = self.root / 'workflow.json'
        for spelling in ('mys' + 'tic', 'mys' + 'tique'):
            for token in (spelling, spelling.upper(), spelling.title()):
                for graph in ({token: 'unused'}, {'metadata': {'title': token}},
                              {'node': {'enabled': False, 'inputs': {'unused': token}}}):
                    with self.subTest(spelling=spelling, graph_field=next(iter(graph))):
                        path.write_text(json.dumps(graph))
                        self.assert_policy(rejected=True)

    def test_escaped_json_metadata_is_rejected(self):
        payload = ''.join('\\u%04x' % ord(char) for char in ('mys' + 'tique'))
        (self.root / 'workflow.json').write_text('{"metadata":"' + payload + '"}')
        self.assert_policy(rejected=True)

    def test_dist_text_is_not_excluded(self):
        dist = self.root / 'dist'
        dist.mkdir()
        (dist / 'README.md').write_text('MYS' + 'TIQUE_adapter.safetensors')
        self.assert_policy(rejected=True)

    def test_workspace_only_directories_remain_excluded(self):
        for directory in SKIP_DIRS:
            path = self.root / directory / 'nested'
            path.mkdir(parents=True)
            (path / 'local.json').write_text('mys' + 'tique')
        self.assert_policy(rejected=False)

    def test_allowed_zip_and_tar_distributions_pass(self):
        graph = json.dumps({'metadata': {'adapters': sorted(ALLOWED_LORAS)}}).encode()
        for suffix in ARCHIVE_SUFFIXES:
            with self.subTest(suffix=suffix):
                name = 'bundle' + suffix
                path = self.root / name
                path.write_bytes(self.archive_bytes(name, [('graphs/main.json', graph),
                                                         ('image.png', b'\x89PNG')]))
                self.assert_policy(rejected=False)

    def test_forbidden_metadata_in_zip_and_tar_distributions_is_rejected(self):
        dist = self.root / 'dist'
        dist.mkdir()
        for suffix in ARCHIVE_SUFFIXES:
            for spelling in ('mys' + 'tic', 'mys' + 'tique'):
                with self.subTest(suffix=suffix, spelling=spelling):
                    name = 'bundle' + suffix
                    path = dist / name
                    payload = json.dumps({'metadata': {'disabled': spelling.upper()}}).encode()
                    path.write_bytes(self.archive_bytes(name, [('cache/unused.json', payload)]))
                    with mock.patch.dict(globals(), ROOT=self.root):
                        self.assertEqual([f'dist/{name}!cache/unused.json'],
                                         _content_policy_offenders())
                    self.assert_policy(rejected=True)
                    path.unlink()

    def test_nested_archives_are_inspected_without_extraction(self):
        payload = json.dumps({'metadata': 'mys' + 'tique'}).encode()
        nested = self.archive_bytes('inner.tar.gz', [('../../escape.json', payload)])
        (self.root / 'bundle.zip').write_bytes(
            self.archive_bytes('bundle.zip', [('inner.tar.gz', nested)]))
        with mock.patch.dict(globals(), ROOT=self.root):
            self.assertEqual(['bundle.zip!inner.tar.gz!../../escape.json'],
                             _content_policy_offenders())
        self.assertEqual(['bundle.zip'], sorted(path.name for path in self.root.iterdir()))
        self.assert_policy(rejected=True)

    def test_corrupt_archives_fail_closed(self):
        for suffix in ARCHIVE_SUFFIXES:
            with self.subTest(suffix=suffix):
                path = self.root / ('broken' + suffix)
                path.write_bytes(b'not an archive')
                self.assert_policy(rejected=True)
                path.unlink()

    def test_archive_limits_fail_closed(self):
        for name in ('bundle.zip', 'bundle.tar', 'bundle.tar.gz'):
            payload = self.archive_bytes(name, [('a.json', b'{}'), ('b.json', b'{}')])
            path = self.root / name
            path.write_bytes(payload)
            limits = {'MAX_ARCHIVE_BYTES': len(payload) - 1,
                      'MAX_MEMBER_BYTES': 1, 'MAX_EXPANDED_BYTES': 3,
                      'MAX_ARCHIVE_MEMBERS': 1, 'MAX_ARCHIVE_DEPTH': 0}
            for constant, limit in limits.items():
                with self.subTest(archive=name, limit=constant):
                    with mock.patch.dict(globals(), {constant: limit}):
                        self.assert_policy(rejected=True)
            path.unlink()

    def test_archive_special_members_fail_closed(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            link = tarfile.TarInfo('alias.json')
            link.type = tarfile.SYMTYPE
            link.linkname = '/not/read'
            archive.addfile(link)
        (self.root / 'links.tar').write_bytes(buffer.getvalue())
        self.assert_policy(rejected=True)
        (self.root / 'links.tar').unlink()
        with zipfile.ZipFile(self.root / 'links.zip', 'w') as archive:
            link = zipfile.ZipInfo('alias.json')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, '/not/read')
        self.assert_policy(rejected=True)


if __name__ == '__main__':
    unittest.main()
