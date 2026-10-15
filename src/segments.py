"""Per-shot inference: pad for the video latent, then restore exact timing."""
from pathlib import Path
import subprocess
import uuid
from media import ffprobe
from config import RIPPLE_PROMPT


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, args)],
                   capture_output=True, check=True, timeout=180)


def latent_frames(count: int) -> int:
    """LTX needs 8n+1 frames; repeat the final frame rather than drop content."""
    return max(9, ((count - 1 + 7) // 8) * 8 + 1)


def _media_path(value: str, work: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else work / "media" / path


def _prepare(video, start, end, folder, fps, padded):
    frame, clip = folder / "source.png", folder / "source.mp4"
    _ffmpeg("-i", video, "-vf", f"select=eq(n\\,{start})", "-frames:v", "1", frame)
    count = end - start + 1
    filters = (f"select=between(n\\,{start}\\,{end}),setpts=N/({fps}*TB),"
               "pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0,"
               f"tpad=stop_mode=clone:stop={padded-count}")
    _ffmpeg("-i", video, "-vf", filters, "-frames:v", padded, "-r", fps,
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", clip)
    return frame, clip


def render_segment(video_path, segment, prompt, client, engine, work, **opts):
    start, end = segment["start"], segment["end"]
    if start < 0 or start > end:
        raise ValueError(f"Invalid segment: {start}..{end}")
    count = end - start + 1
    padded = latent_frames(count)
    fps = ffprobe(video_path)["fps"]
    folder = work / "media" / f"shot_{uuid.uuid4().hex}"
    folder.mkdir(parents=True)
    frame, clip = _prepare(video_path, start, end, folder, fps, padded)
    frame_ref = client.assets.from_file(frame).as_reference()
    edited = engine.edit_frame(client, frame_ref, prompt, **opts.get("edit", {}))
    video_ref = client.assets.from_file(clip).as_reference()
    edited_ref = client.assets.from_file(_media_path(edited, work)).as_reference()
    propagation = {**opts.get("propagate", {}), "frames": padded, "fps": fps}
    result = engine.propagate(client, video_ref, edited_ref,
                              opts.get("ripple_prompt", RIPPLE_PROMPT), **propagation)
    rendered = _media_path(result, work)
    if ffprobe(rendered)["frames"] < count:
        raise RuntimeError(f"Inference returned fewer than {count} frames")
    dest = folder / "edited.mp4"
    _ffmpeg("-i", rendered, "-frames:v", count, "-an", "-r", fps,
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", dest)
    return str(dest.resolve())
