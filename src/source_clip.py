"""CPU-only explicit excerpt validation shared by both Swap studios. Originals are never changed or moved."""
import json
import math
import subprocess
from pathlib import Path

from h3_capsule import digest_file
from h3_media import AUDIO_ARGS, ffmpeg, has_audio
from media import ffprobe
from media_probe import consistent_duration

MAX_CLIP_SECONDS = 15


def probe_source(path):
    """Measure the VIDEO timeline, never a container duration extended by audio.

    Some WebM/MKV streams have no duration; in that case use video packet PTS
    endpoints, not the format duration (which can include a long AAC tail).
    """
    info = ffprobe(path)
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=duration,start_time:packet=pts_time,duration_time',
         '-of', 'json', str(path)], capture_output=True, text=True, check=True, timeout=180)
    measured = json.loads(result.stdout)
    duration = measured['streams'][0].get('duration')
    if duration in (None, 'N/A'):
        packets = measured.get('packets', [])
        starts = [float(p['pts_time']) for p in packets if 'pts_time' in p]
        ends = [float(p['pts_time']) + float(p.get('duration_time', 0))
                for p in packets if 'pts_time' in p]
        if not starts:
            raise ValueError('Cannot measure the H3 video timeline')
        duration = max(ends) - min(starts)
    duration = consistent_duration(duration, info['frames'], info['fps'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Cannot measure the H3 video duration')
    return {**info, 'duration': duration,
            'video_start_seconds': float(measured['streams'][0].get('start_time', 0))}


def validate_selection(info, start=None, end=None, *, label="H3"):
    """Return the requested interval, or refuse rather than silently trim it."""
    duration = float(info['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Cannot measure the H3 video duration')
    if start is None and end is None:
        if duration > MAX_CLIP_SECONDS:
            raise ValueError(f'{label} sources longer than 15 seconds require an explicit excerpt')
        return 0.0, duration
    if start is None or end is None:
        raise ValueError('Provide both clip_start_seconds and clip_end_seconds')
    start, end = float(start), float(end)
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError(f'{label} excerpt bounds must be finite seconds')
    if start < 0 or end <= start or end > duration:
        raise ValueError(f'{label} excerpt must be a positive interval within the source video')
    if end - start > MAX_CLIP_SECONDS:
        raise ValueError(f'{label} excerpts must be at most 15 seconds')
    return start, end


def require_short_source(path):
    """Submission/worker/replay guard: no extraction and no SDK access."""
    info = probe_source(path)
    validate_selection(info)
    if info['duration'] * 24 < 1:
        raise ValueError('H3 source must contain at least one frame at 24fps')
    return info


def extract_excerpt(source, destination, info, start, end):
    """Re-encode precisely the same video/audio interval, retaining its dimensions.

    A common zero-based input timeline preserves stream offsets; subtract the
    chosen start from both PTS clocks. No scale, fps conversion or auto-selection.
    """
    start, end = validate_selection(info, start, end)
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve() or destination.exists():
        raise ValueError('H3 excerpt destination must be a new file')
    original_hash = digest_file(source)
    selection = {'schema_version': 1, 'start_seconds': start, 'end_seconds': end,
                 'original_duration_seconds': info['duration'],
                 'original_sha256': original_hash, 'original_size_bytes': source.stat().st_size}
    # Preserve relative stream offsets, including audio that begins after video.
    # The user's coordinates are relative to the first video frame, not audio.
    origin = info.get('video_start_seconds', 0)
    absolute_start, absolute_end = origin + start, origin + end
    vf = (f'trim=start={absolute_start:.17g}:end={absolute_end:.17g},'
          f'setpts=PTS-({absolute_start:.17g})/TB')
    audio = []
    if has_audio(source):
        audio = ['-map', '0:a:0', '-af',
                 f'atrim=start={absolute_start:.17g}:end={absolute_end:.17g},'
                 f'asetpts=PTS-({absolute_start:.17g})/TB,aresample=async=1:first_pts=0',
                 *AUDIO_ARGS]
    # Browser-compatible for ordinary dimensions; retain odd dimensions exactly
    # rather than silently pad/crop the user's accepted source.
    pixel_format = 'yuv420p' if info['width'] % 2 == info['height'] % 2 == 0 else 'yuv444p'
    try:
        ffmpeg('-copyts', '-i', source, '-map', '0:v:0', '-vf', vf, *audio,
               '-c:v', 'libx264', '-crf', 18, '-pix_fmt', pixel_format,
               '-fps_mode', 'vfr', '-t', f'{end-start:.17g}', '-movflags', '+faststart', destination)
        effective = require_short_source(destination)
        if (effective['width'], effective['height']) != (info['width'], info['height']):
            raise ValueError('H3 excerpt dimensions changed')
        if digest_file(source) != original_hash:
            raise ValueError('H3 original source changed during extraction')
        return effective, selection
    except Exception:
        destination.unlink(missing_ok=True)
        raise
