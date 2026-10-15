"""Shot detection through FFmpeg; frame ranges are inclusive."""
import json
import re
import subprocess
from pathlib import Path

def detect_scenes(video_path: str | Path, threshold: float = 0.3) -> list[dict]:
    """Detect shot boundaries using ffmpeg scene detection.

    Returns a list of segments: [{"start": int, "end": int}, ...]
    Frame indices are 0-based, inclusive.
    """
    video_path = str(video_path)

    from media import ffprobe
    info = ffprobe(video_path)
    fps, total_frames = info["fps"], info["frames"]

    # Run ffmpeg scene detection
    result = subprocess.run(
        ["ffmpeg", "-i", video_path, "-vf", f"select='gt(scene,{threshold})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True, timeout=180
    )

    # Parse scene change timestamps from stderr
    cut_frames = []
    for line in result.stderr.splitlines():
        match = re.search(r"pts_time:([\d.]+)", line)
        if match:
            cut_frames.append(round(float(match.group(1)) * fps))

    # Build segments
    segments = []
    prev = 0
    for cf in cut_frames:
        if cf > prev:
            segments.append({"start": prev, "end": cf - 1})
        prev = cf
    if prev < total_frames:
        segments.append({"start": prev, "end": total_frames - 1})

    return segments
