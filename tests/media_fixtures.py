"""Small, real FFmpeg fixtures for CPU media tests; no downloaded clips or GPU."""
import subprocess
from pathlib import Path


CUT_FRAME = 68
TOTAL_FRAMES = 121
FRAME_RATE = 24
FRAME_SIZE = 64
TWO_SHOTS = [
    {"start": 0, "end": CUT_FRAME - 1},
    {"start": CUT_FRAME, "end": TOTAL_FRAMES - 1},
]


def make_test_video(directory: Path, *, two_shots: bool = True) -> Path:
    """Write 121 black frames, switching to white at frame 68 if requested.

    The caller owns the directory (normally a TemporaryDirectory). The constant
    colors give scene detection an exact, unambiguous boundary at a low cost.
    """
    path = Path(directory) / ("two_shots.mp4" if two_shots else "single_shot.mp4")
    command = [
        "ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i",
        f"color=c=black:s={FRAME_SIZE}x{FRAME_SIZE}:r={FRAME_RATE}",
    ]
    if two_shots:
        command += [
            "-vf", f"drawbox=c=white:t=fill:enable='gte(n,{CUT_FRAME})'",
        ]
    command += [
        "-frames:v", str(TOTAL_FRAMES), "-an", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-threads", "1", str(path),
    ]
    subprocess.run(command, capture_output=True, check=True, timeout=30)
    return path
