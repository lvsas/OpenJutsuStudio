"""H3-only media normalization, last-frame padding and original-audio assembly."""
import subprocess
import json
from pathlib import Path
from media import ffprobe
from h3_graphs import h3_frames


def has_audio(path):
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a',
                            '-show_entries', 'stream=codec_type', '-of', 'json', str(path)],
                           capture_output=True, text=True, check=True, timeout=30)
    return bool(json.loads(probe.stdout).get('streams'))


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *map(str, args)],
                   capture_output=True, check=True, timeout=180)


def prepare_source(source, folder):
    """Normalize to 24fps, then pad clones to 17k+5; do not drop source frames."""
    normalized, padded = folder / 'normalized.mp4', folder / 'padded.mp4'
    ffmpeg('-i', source, '-map', '0:v:0', '-vf',
           'fps=24,pad=ceil(iw/2)*2:ceil(ih/2)*2,setsar=1',
           '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', normalized)
    count = ffprobe(normalized)['frames']
    length = h3_frames(count)
    ffmpeg('-i', normalized, '-vf', f'tpad=stop_mode=clone:stop={length-count}',
           '-frames:v', length, '-r', 24, '-an', '-c:v', 'libx264', padded)
    if ffprobe(padded)['frames'] != length:
        raise ValueError('H3 source padding failed')
    return padded, count, length


def finish_result(rendered, source, destination, count):
    """Trim video to unpadded length and mux only the optional original audio."""
    ffmpeg('-i', rendered, '-i', source, '-map', '0:v:0', '-map', '1:a:0?',
           '-vf', f'trim=end_frame={count},setpts=N/(24*TB)', '-r', 24,
           '-t', count / 24, '-c:v', 'libx264', '-crf', 18, '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', destination)
    return Path(destination)


def validate_result(path, count, width, height):
    info = ffprobe(path)
    if (info['frames'] != count or abs(info['fps'] - 24) > 0.001
            or info['width'] != width or info['height'] != height):
        raise ValueError('H3 output timing or dimensions do not match the frozen recipe')
