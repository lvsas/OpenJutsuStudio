"""Measure whether a generated take still moves like the performance it replaced.

Two takes can look plausible in a still and be worthless in motion: frozen,
stuttering, or playing at the wrong speed. This module compares frame-to-frame
motion energy of the result against the source it was built from, on the same
window, and reports a bounded score with explicit flags.

It is deliberately a *measurement*, not a taste judgement: it cannot tell you the
faces are good. It can tell you the performance was not preserved.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

GRID, HEIGHT = 96, 54   # fixed analysis grid: same geometry for both clips, cheap to decode
RATE = 12           # frames per second analysed
FROZEN_RATIO = 0.15  # result moves less than 15 % of the source
WILDMOTION_RATIO = 2.5  # result moves more than 2.5x the source


@dataclass(frozen=True)
class TakeScore:
    score: int                 # 0-100, 100 = same motion energy as the source
    source_motion: float       # mean absolute frame-to-frame change, 0-255
    result_motion: float
    ratio: float               # result / source
    flags: tuple[str, ...]
    frames_compared: int

    def as_dict(self) -> dict:
        body = asdict(self)
        body['flags'] = list(self.flags)
        return body


def _frames(path: Path, start: float, duration: float) -> bytes:
    proc = subprocess.run(
        ['ffmpeg', '-v', 'error', '-nostdin', '-ss', f'{start:.3f}', '-t', f'{duration:.3f}',
         '-i', str(path), '-vf', f'fps={RATE},scale={GRID}:{HEIGHT},format=gray',
         '-f', 'rawvideo', '-pix_fmt', 'gray', '-'],
        capture_output=True, timeout=180)
    if proc.returncode:
        raise ValueError(f'could not decode {path.name}: {proc.stderr[:200].decode(errors="replace")}')
    return proc.stdout


def _motion(raw: bytes) -> tuple[float, int]:
    """Mean absolute difference between consecutive frames."""
    # frame height is unknown here, so derive it from the payload size per frame:
    # every frame is GRID * h bytes, and the payload is a whole number of frames.
    frame = GRID * HEIGHT
    if len(raw) < frame * 2:
        return 0.0, 0
    count = len(raw) // frame
    diffs = 0
    previous = raw[0:frame]
    for index in range(1, count):
        current = raw[index * frame:(index + 1) * frame]
        diffs += sum(abs(a - b) for a, b in zip(current, previous))
        previous = current
    return diffs / ((count - 1) * frame), count


def score_take(source: str | Path, result: str | Path, *, start: float = 0.0,
               duration: float | None = None) -> TakeScore:
    """Compare the result's motion energy against the source over the same window."""
    source, result = Path(source), Path(result)
    for path in (source, result):
        if not path.is_file():
            raise ValueError(f'missing clip: {path.name}')
    if duration is None:
        duration = float(subprocess.check_output(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=nw=1:nk=1', str(result)], text=True).strip())
    # never compare more than the source actually contains
    source_duration = float(subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=nw=1:nk=1', str(source)], text=True).strip())
    window = max(0.5, min(duration, source_duration - start))
    src_motion, src_frames = _motion(_frames(source, start, window))
    out_motion, out_frames = _motion(_frames(result, start, window))
    frames = min(src_frames, out_frames)

    flags: list[str] = []
    if src_motion < 0.35:
        # the source itself is close to still: a motion score would be noise
        return TakeScore(score=50, source_motion=round(src_motion, 3),
                         result_motion=round(out_motion, 3), ratio=0.0,
                         flags=('source-still',), frames_compared=frames)
    ratio = out_motion / src_motion
    if ratio < FROZEN_RATIO:
        flags.append('frozen')
    elif ratio < 0.5:
        flags.append('low-motion')
    if ratio > WILDMOTION_RATIO:
        flags.append('wild-motion')
    # 1.0 is perfect; drift in either direction costs, but a slow take is worse
    penalty = abs(ratio - 1.0)
    score = max(0, min(100, round(100 - penalty * 100)))
    return TakeScore(score=score, source_motion=round(src_motion, 3),
                     result_motion=round(out_motion, 3), ratio=round(ratio, 3),
                     flags=tuple(flags), frames_compared=frames)


if __name__ == '__main__':
    import sys
    print(json.dumps(score_take(sys.argv[1], sys.argv[2]).as_dict(), indent=2))
