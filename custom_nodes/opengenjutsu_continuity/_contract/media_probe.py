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
    data = json.loads(result.stdout)
    if not data.get('streams'):
        raise ValueError('No video stream')
    stream = data['streams'][0]
    rate = stream.get('avg_frame_rate')
    if not rate or rate == '0/0':
        rate = stream.get('r_frame_rate', '0/1')
    fps = float(Fraction(rate))
    count = int(stream.get('nb_read_frames') or 0)
    if fps <= 0 or count <= 0:
        raise ValueError('Cannot determine video frame count or frame rate')
    duration = stream.get('duration') or data.get('format', {}).get('duration')
    return {'width': int(stream['width']), 'height': int(stream['height']),
            'fps': fps, 'frames': count, 'duration': float(duration or count / fps)}


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
