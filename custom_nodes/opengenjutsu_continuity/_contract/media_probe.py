"""Configuration-free FFprobe metadata inspection.

Importing this module creates no workspace directories, changes no environment
variables and connects to no service. The media facade re-exports this function
for compatibility with existing callers.
"""
import json
from fractions import Fraction
from pathlib import Path
import subprocess


def _probe(path: str | Path, input_options: tuple[str, ...] = ()) -> dict:
    """Count frames with an explicit input policy supplied by the caller."""
    result = subprocess.run(
        ['ffprobe', '-v', 'error', *input_options, '-count_frames', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height,nb_read_frames,avg_frame_rate,r_frame_rate,duration:format=duration',
         '-of', 'json', str(path)], capture_output=True, text=True, check=True, timeout=180)
    return _interpret(json.loads(result.stdout))


#: A declared rate and an average rate this close describe the same footage.
RATE_TOLERANCE = 0.02
#: A container may omit the last frame's duration; that is one frame, not a drift.
FRAME_SLACK = 1.0


def consistent_duration(reported, frames: int, fps: float) -> float:
    """Prefer the frame count when a container reports one frame less."""
    derived = frames / fps
    if reported in (None, 'N/A', ''):
        return derived
    reported = float(reported)
    return derived if abs(reported - derived) <= FRAME_SLACK / fps + 1e-6 else reported


def _rational(value) -> Fraction:
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def _interpret(payload: dict) -> dict:
    """Turn one ffprobe payload into width, height, fps, frames and duration.

    ``avg_frame_rate`` is *frames / duration*, so a container that ends one
    frame short reports 24.338 fps for footage written at 24. The declared
    ``r_frame_rate`` stays exact, and wins whenever the two agree within
    ``RATE_TOLERANCE``; a wider gap means the frame rate really does vary.
    """
    streams = payload.get('streams') or []
    if not streams:
        raise ValueError('No video stream')
    stream = streams[0]
    declared = _rational(stream.get('r_frame_rate') or '0/1')
    average = _rational(stream.get('avg_frame_rate') or '0/1')
    if average <= 0:
        average = declared
    if average <= 0:
        raise ValueError('Cannot determine video frame count or frame rate')
    same_footage = declared > 0 and abs(declared - average) <= average * RATE_TOLERANCE
    fps = float(declared if same_footage else average)
    count = int(stream.get('nb_read_frames') or 0)
    if count <= 0:
        raise ValueError('Cannot determine video frame count or frame rate')
    reported = stream.get('duration') or payload.get('format', {}).get('duration')
    return {'width': int(stream['width']), 'height': int(stream['height']),
            'fps': fps, 'frames': count,
            'duration': consistent_duration(reported, count, fps)}


def ffprobe(path: str | Path) -> dict:
    """Compatibility probe for existing MP4/WebM/MKV application callers."""
    return _probe(path)


def probe_mp4(path: str | Path) -> dict:
    """Decode only a local MOV/MP4 container, never playlists/external tracks.

    Force the demuxer rather than trusting a suffix or format autodetection.
    File-only protocols also block network resources; the MOV demuxer's two
    explicit dref options disable external track and absolute-alias support.
    """
    return _probe(path, ('-protocol_whitelist', 'file', '-f', 'mov',
                         '-enable_drefs', '0', '-use_absolute_path', '0'))
