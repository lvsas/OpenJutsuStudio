"""FFmpeg-only scene detection and media operations."""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from config import WORK

from scenes import detect_scenes


def ffprobe(path: str | Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,nb_frames,r_frame_rate,duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    fr = s.get("r_frame_rate", "24/1")
    num, _, den = fr.partition("/")
    fps = float(num) / float(den or 1)
    return {"width": int(s["width"]), "height": int(s["height"]),
            "fps": fps, "frames": int(s.get("nb_frames") or 0),
            "duration": float(s.get("duration") or 0)}


def extract_first_frame(video: Path, dest: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                    "-vf", "select=eq(n\\,0)", "-vframes", "1", str(dest)],
                   check=True)
    return dest


def extract_segment_frames(video: str | Path, segments: list[dict],
                          output_dir: Path | None = None) -> list[Path]:
    """Extract the first frame from each detected segment.

    Args:
        video: Path to input video
        segments: List of {"start": int, "end": int} from detect_scenes()
        output_dir: Where to save frames (default: WORK/media)

    Returns:
        List of paths to extracted frame images
    """
    video = str(video)
    if output_dir is None:
        output_dir = WORK / "media"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    for i, seg in enumerate(segments):
        start_frame = seg["start"]
        dest = output_dir / f"seg_{i:03d}_f{start_frame:04d}.png"
        # Use ffmpeg to extract specific frame
        select_filter = f"select=eq(n,{start_frame})".replace(",", "\\,")
        subprocess.run(
            ["ffmpeg", "-y", "-i", video, "-vf", select_filter,
             "-vframes", "1", str(dest)],
            capture_output=True, check=True
        )
        frames.append(dest)

    return frames


def merge_segments(segment_paths: list[str | Path], output_path: Path | None = None) -> str | None:
    """Merge multiple segment videos into one using ffmpeg concat demuxer.

    Args:
        segment_paths: List of paths to segment video files
        output_path: Where to save merged video (default: WORK/media/merged_<timestamp>.mp4)

    Returns:
        Path to merged video file, or None if input list is empty
    """
    if not segment_paths:
        return None
    if len(segment_paths) == 1:
        return str(segment_paths[0])

    if output_path is None:
        output_path = WORK / "media" / f"merged_{int(time.time())}.mp4"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Create concat list file
    list_file = output_path.parent / f"concat_{int(time.time())}.txt"
    with open(list_file, "w") as f:
        for seg in segment_paths:
            # Escape single quotes in path for ffmpeg concat
            escaped = str(seg).replace("'", "'\''")
            f.write(f"file '{escaped}'\n")

    # Run ffmpeg concat
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c", "copy", str(output_path)],
        capture_output=True, check=True
    )

    # Clean up list file
    list_file.unlink(missing_ok=True)

    return str(output_path)


def has_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def upscale_video(input_path: str | Path, output_path: str | Path | None = None,
                  scale: float = 2.0) -> str:
    """Upscale video resolution using ffmpeg scale filter.

    Args:
        input_path: Path to input video
        output_path: Where to save upscaled video (default: WORK/media/upscaled_<timestamp>.mp4)
        scale: Upscale factor (2.0 = double resolution)

    Returns:
        Path to upscaled video file
    """
    input_path = str(input_path)
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")
    if output_path is None:
        output_path = WORK / "media" / f"upscaled_{int(time.time())}.mp4"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get input dimensions
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", input_path],
        capture_output=True, text=True, check=True
    )
    info = json.loads(probe.stdout)
    stream = info["streams"][0]
    width = int(stream["width"])
    height = int(stream["height"])

    new_width = int(width * scale)
    new_height = int(height * scale)

    # Use ffmpeg scale filter with lanczos for quality
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_path,
         "-vf", f"scale={new_width}:{new_height}:flags=lanczos",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-c:a", "copy", str(output_path)],
        capture_output=True, check=True
    )

    return str(output_path)


