#!/usr/bin/env python3
"""Deterministically bundle only this pack and four exact private contracts.

No app imports, dependency installation, sys.path mutation or network access.
Internal absolute imports are rewritten by an AST-whitelisted source edit;
all other source bytes (including comments) are preserved.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'custom_nodes' / 'opengenjutsu_continuity'
CONTRACTS = ('timeline_artifacts', 'safetensor_header', 'h3_conditioning', 'media_probe')
SOURCES = ('__init__.py', 'nodes.py', 'family.py', 'LICENSE', 'README.md')


def private_contract(source: str) -> str:
    """Change ONLY whitelisted internal import statements, fail on new deps."""
    tree = ast.parse(source)
    edits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                raise ValueError('Contract import layout changed; review required')
            if node.module in CONTRACTS:
                if node.lineno != node.end_lineno:
                    raise ValueError('Multiline internal import needs explicit builder review')
                replacement = ast.unparse(ast.ImportFrom(module=node.module, names=node.names, level=1))
                edits.append((node.lineno, node.col_offset, node.end_col_offset, replacement))
            elif node.module.split('.')[0] not in sys.stdlib_module_names:
                raise ValueError('Contract added a non-stdlib dependency; review required')
        elif isinstance(node, ast.Import):
            if any(alias.name.split('.')[0] not in sys.stdlib_module_names for alias in node.names):
                raise ValueError('Contract added a non-stdlib dependency; review required')
    lines = source.splitlines(keepends=True)
    for line, start, end, replacement in sorted(edits, reverse=True):
        lines[line - 1] = lines[line - 1][:start] + replacement + lines[line - 1][end:]
    result = ''.join(lines)
    compile(result, '<private-contract>', 'exec')
    return result


def contract_payloads():
    files = {'_contract/__init__.py': b'"""Generated private CPU contracts; regenerate with the pack builder."""\n'}
    provenance = {}
    for name in CONTRACTS:
        raw = (ROOT / 'src' / f'{name}.py').read_bytes()
        transformed = private_contract(raw.decode('utf-8')).encode('utf-8')
        files[f'_contract/{name}.py'] = transformed
        provenance[f'{name}.py'] = {'source_sha256': hashlib.sha256(raw).hexdigest(),
                                   'bundle_sha256': hashlib.sha256(transformed).hexdigest()}
    files['_contract/provenance.json'] = (json.dumps(provenance, sort_keys=True, indent=2) + '\n').encode()
    return files


def refresh_contracts():
    for relative, data in contract_payloads().items():
        path = PACK / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def payloads():
    generated = contract_payloads()
    for relative, expected in generated.items():
        if not (PACK / relative).is_file() or (PACK / relative).read_bytes() != expected:
            raise ValueError('Bundled contract drift; run builder --refresh-contracts after review')
    return {**{name: (PACK / name).read_bytes() for name in SOURCES}, **generated}


def archive_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        for relative, data in sorted(payloads().items()):
            info = zipfile.ZipInfo('opengenjutsu_continuity/' + relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-contracts', action='store_true')
    parser.add_argument('--check', action='store_true', help='Verify checked-in zip byte-for-byte, do not write it')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / 'opengenjutsu-continuity.zip')
    args = parser.parse_args()
    if args.refresh_contracts:
        refresh_contracts()
        if not all((PACK / name).is_file() for name in SOURCES):
            print('Private contracts refreshed; pack sources not yet complete')
            return
    data = archive_bytes()
    if args.check:
        if args.output.read_bytes() != data:
            raise SystemExit('Package drift: rebuild required')
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
    print(json.dumps({'archive': args.output.name, 'bytes': len(data),
                      'sha256': hashlib.sha256(data).hexdigest(), 'checked': args.check}, sort_keys=True))


if __name__ == '__main__':
    main()
