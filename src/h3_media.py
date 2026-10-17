"""H3-only media normalization, last-frame padding and soundtrack assembly.

Source audio is conditioning input for the H3 reference node, not a local
afterthought: the prepared clip keeps its soundtrack so both the reference node
and the combine node receive it, matching the measured winning A/B arm.
"""
import subprocess
import json
from pathlib import Path
from media import ffprobe
from h3_graphs import h3_frames

AUDIO_ARGS = ['-c:a', 'aac', '-b:a', '192k']


def has_audio(path):
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a',
                            '-show_entries', 'stream=codec_type', '-of', 'json', str(path)],
                           capture_output=True, text=True, check=True, timeout=30)
    return bool(json.loads(probe.stdout).get('streams'))


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *map(str, args)],
                   capture_output=True, check=True, timeout=180)


def prepare_source(source, folder):
    """Normalize to 24fps, keep the optional soundtrack, pad clones to 17k+5."""
    normalized, padded = folder / 'normalized.mp4', folder / 'padded.mp4'
    ffmpeg('-i', source, '-map', '0:v:0', '-map', '0:a:0?', '-vf',
           'fps=24,pad=ceil(iw/2)*2:ceil(ih/2)*2,setsar=1',
           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', *AUDIO_ARGS, normalized)
    count = ffprobe(normalized)['frames']
    length = h3_frames(count)
    pad = ['-map', '0:v:0', '-vf', f'tpad=stop_mode=clone:stop={length-count}',
           '-frames:v', length, '-r', 24]
    if has_audio(normalized):
        # Video clones the last frame, so audio is padded to the same length.
        pad += ['-map', '0:a:0', '-af', 'apad', '-t', length / 24, *AUDIO_ARGS]
    ffmpeg('-i', normalized, *pad, '-c:v', 'libx264', padded)
    if ffprobe(padded)['frames'] != length:
        raise ValueError('H3 source padding failed')
    return padded, count, length


def finish_result(rendered, source, destination, count):
    """Trim the padded render to the unpadded length, keeping its own soundtrack.

    The render already carries the conditioned source audio. Local muxing is only
    a fallback for a render that returned no audio track, so a track is never doubled.
    """
    seconds = f'{count / 24:.6f}'
    audio = f'atrim=end={seconds},asetpts=N/SR/TB'
    inputs, audio_args = ['-i', rendered], []
    if has_audio(rendered):
        audio_args = ['-map', '0:a:0', '-af', audio]
    elif has_audio(source):
        inputs += ['-i', source]
        audio_args = ['-map', '1:a:0', '-af', audio]
    ffmpeg(*inputs, '-map', '0:v:0', *audio_args,
           '-vf', f'trim=end_frame={count},setpts=N/(24*TB)', '-r', 24, '-t', seconds,
           '-c:v', 'libx264', '-crf', 18, '-pix_fmt', 'yuv420p',
           *(AUDIO_ARGS if audio_args else []),
           '-movflags', '+faststart', destination)
    return Path(destination)


def validate_result(path, count, width, height):
    info = ffprobe(path)
    if (info['frames'] != count or abs(info['fps'] - 24) > 0.001
            or info['width'] != width or info['height'] != height):
        raise ValueError('H3 output timing or dimensions do not match the frozen recipe')
