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

    # Get video info (fps, total frames)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate,nb_frames",
         "-of", "json", video_path],
        capture_output=True, text=True, check=True
    )
    info = json.loads(probe.stdout)
    stream = info["streams"][0]
    fps_parts = stream["r_frame_rate"].split("/")
    fps = int(fps_parts[0]) / int(fps_parts[1]) if len(fps_parts) == 2 else float(fps_parts[0])
    total_frames = int(stream.get("nb_frames", 0))

    # If nb_frames not available, estimate from duration
    if total_frames == 0:
        dur_probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", video_path],
            capture_output=True, text=True, check=True
        )
        duration = float(json.loads(dur_probe.stdout)["format"]["duration"])
        total_frames = int(duration * fps)

    # Run ffmpeg scene detection
    result = subprocess.run(
        ["ffmpeg", "-i", video_path, "-vf", f"select='gt(scene,{threshold})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True
    )

    # Parse scene change timestamps from stderr
    cut_frames = []
    for line in result.stderr.splitlines():
        match = re.search(r"pts_time:([\d.]+)", line)
        if match:
            cut_frames.append(int(float(match.group(1)) * fps))

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
