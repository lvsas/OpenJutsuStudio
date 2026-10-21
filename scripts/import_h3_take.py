#!/usr/bin/env python3
"""Operator-only import into WORK/timeline/continuable-takes (no API/path browser).

Example, using only an isolated scratch WORK for proof:
  python3 scripts/import_h3_take.py --video /source/take.mp4 \
    --mctx /source/take.mctx.safetensors --cond /source/take.cond.safetensors \
    --root /source --work /scratch/proof-work --embedded-prompt \
    --graph-completeness complete --source-job 2218 --label operator-proof

An explicit --captured-graph JSON file is an alternative to --embedded-prompt;
--without-graph records unavailable evidence, never an invented recipe. Nothing
queries a database or reconstructs an old execution from a current workflow.
Stdout contains path-free public metadata only. Errors intentionally omit local
paths and graph contents. The graph and full native metadata stay private.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Import only pure CPU contracts, never app/config/SDK startup.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from continuable_take import (TakePublicationUncertain, get_validated_family, import_family,
                              read_captured_graph, read_embedded_prompt)


def report_visible(take_id, phase):
    status = ('publication_visible_durability_unconfirmed' if phase == 'directory_sync'
              else 'publication_visible_validation_unconfirmed')
    print(json.dumps({'status': status, 'take_id': take_id,
        'recovery': 'Validate this exact Take ID before retrying; do not repeat an anonymous import.'}),
        file=sys.stderr)
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--video', required=True, type=Path)
    parser.add_argument('--mctx', required=True, type=Path)
    parser.add_argument('--cond', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path, help='Explicit allowed source-artifact root')
    parser.add_argument('--work', required=True, type=Path, help='Explicit destination WORK; no app-config default')
    parser.add_argument('--take-id', help='Exactly 32 lowercase hexadecimal characters; omitted means UUID hex')
    evidence = parser.add_mutually_exclusive_group(required=True)
    evidence.add_argument('--embedded-prompt', action='store_true', help='Capture the actual MP4 prompt tag')
    evidence.add_argument('--captured-graph', type=Path, help='Explicit actual-execution JSON capture')
    evidence.add_argument('--without-graph', action='store_true', help='Record graph evidence as unavailable')
    parser.add_argument('--graph-completeness', choices=('unknown', 'partial', 'complete'), default='unknown',
                        help='Operator attestation, NOT an app replay/compatibility approval')
    parser.add_argument('--source-job', help='Plain source job identifier, never a URL')
    parser.add_argument('--label', help='Plain operator label (letters, digits, underscore, dash)')
    args = parser.parse_args(argv)
    record = None
    try:
        video = args.video if args.video.is_absolute() else args.root / args.video
        if args.embedded_prompt:
            graph = read_embedded_prompt(video)
        elif args.captured_graph:
            graph = read_captured_graph(args.captured_graph)
        else:
            graph = None
        kwargs = {} if args.take_id is None else {'take_id': args.take_id}
        record = import_family(args.video, args.mctx, args.cond, root=args.root, work=args.work,
            captured_graph=graph, graph_completeness=args.graph_completeness,
            graph_source='mp4_prompt' if args.embedded_prompt else 'operator_capture',
            source_job=args.source_job, operator_label=args.label, **kwargs)
        # Read back the exact destination and independently validate every role
        # before reporting CLI success; metadata listing remains explicitly stale.
        verified = get_validated_family(args.work, record.take_id)
        print(json.dumps({'take': verified.record.to_manifest(),
                          'validation': {'scope': 'capsule-file-integrity-and-media-geometry',
                                         'freshly_validated': True, 'runtime_compatibility': 'unproven'}},
                         indent=2, sort_keys=True))
        return 0
    except TakePublicationUncertain as exc:
        return report_visible(exc.take_id, exc.phase)
    except Exception as exc:
        if record is not None:
            return report_visible(record.take_id, 'validation')
        # FFprobe/OSError messages may contain paths, filenames or graph values.
        print(f'Import refused ({type(exc).__name__}); no runtime/replay claim made.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
