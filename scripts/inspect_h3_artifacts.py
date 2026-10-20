#!/usr/bin/env python3
"""Inspect a local H3 artifact family without ComfyUI, torch, or GPU access."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from timeline_artifacts import ArtifactValidationError, validate_h3_artifact_set


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='Trusted local media directory')
    parser.add_argument('--video', required=True, type=Path, help='MP4, absolute or relative to root')
    parser.add_argument('--mctx', required=True, type=Path, help='MCTX safetensors, absolute or relative to root')
    parser.add_argument('--conditioning', required=True, type=Path,
                        help='COND safetensors, absolute or relative to root')
    args = parser.parse_args(argv)
    try:
        result = validate_h3_artifact_set(args.video, args.mctx, args.conditioning, root=args.root)
    except ArtifactValidationError as exc:
        print(json.dumps({'error': {'code': exc.code, 'role': exc.role, 'message': str(exc)}}),
              file=sys.stderr)
        return 1
    print(json.dumps(result.to_manifest(), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
