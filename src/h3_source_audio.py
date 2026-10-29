"""Exact original-song preparation for the existing native continuation chain.

The source is an identified retained Swap upload, never a browser path. The
prepared window is frozen in the operation graph/Take's existing private capture.
No padding, tempo change, external remux, registry or inference happens here.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import wave

from continuable_take import _open_file, _read_json, _source
from h3_av_state import require_continuable_child, state_from_family, tail_window

RATE = 32000
POLICY = 'original-source-v1'
METADATA_KEY = 'opengenjutsu_source_audio'
_KEYS = {'policy', 'source_job', 'source_sha256', 'raw_video_start', 'start_sample', 'sample_count'}


def audio_window(parent, raw_frames, raw_video_origin):
    """Project source clocks using the same native state/pin policy as the saver."""
    child = require_continuable_child(parent, raw_frames)
    first_frame, first_tick, _, _ = tail_window(parent)
    origin = Fraction(raw_video_origin)
    audio_start = origin + Fraction(first_tick, 40) + parent.audio_phase / 40
    return {'raw_video_start': str(origin + Fraction(first_frame, 24)),
            'start_sample': round(audio_start * RATE),
            'sample_count': child.audio_ticks * (RATE // 40)}


def require_audio_capacity(window, duration):
    if (window['start_sample'] < 0 or window['sample_count'] <= 0
            or Fraction(window['start_sample'] + window['sample_count'], RATE) > Fraction(duration)):
        raise ValueError('The original soundtrack does not cover this extension. Choose a shorter duration or another take; nothing was submitted.')


def extract_audio_window(source, destination, window):
    """Decode/resample before exact sample trim; refuse short output, never pad."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError('A new private soundtrack destination is required.')
    start, count = window['start_sample'], window['sample_count']
    if type(start) is not int or start < 0 or type(count) is not int or not 0 < count <= RATE * 150:
        raise ValueError('The soundtrack sample window is invalid.')
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-protocol_whitelist', 'file',
        '-i', str(source), '-map', '0:a:0', '-af',
        f'aresample={RATE},atrim=start_sample={start}:end_sample={start + count},asetpts=PTS-STARTPTS',
        '-ac', '2', '-c:a', 'pcm_s24le', str(destination)],
        check=True, capture_output=True, timeout=180)
    with wave.open(str(destination), 'rb') as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getnframes()) != (RATE, 2, count):
            raise ValueError('The decoded original soundtrack is too short; no silence was added and nothing was submitted.')


def validate_audio_context(context):
    """Validate the private frozen contract, not arbitrary imported graph commands."""
    if (not isinstance(context, dict) or set(context) != _KEYS or context['policy'] != POLICY
            or not isinstance(context['source_job'], str) or not re.fullmatch(r'[0-9a-f]{32}', context['source_job'])
            or not isinstance(context['source_sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', context['source_sha256'])
            or not isinstance(context['raw_video_start'], str) or len(context['raw_video_start']) > 64
            or not re.fullmatch(r'\d+(?:/\d+)?', context['raw_video_start'])
            or type(context['start_sample']) is not int or context['start_sample'] < 0
            or type(context['sample_count']) is not int or not 0 < context['sample_count'] <= RATE * 150):
        raise ValueError('The saved soundtrack context could not be verified.')
    try:
        Fraction(context['raw_video_start'])
    except (ValueError, ZeroDivisionError):
        raise ValueError('The saved soundtrack clock could not be verified.') from None
    return dict(context)


def _source_file(work, job_id, expected_hash=None):
    root = Path(work).absolute()
    job = _read_json(root / 'jobs' / f'{job_id}.json')
    if job.get('id') != job_id:
        raise ValueError('The original soundtrack origin could not be verified.')
    meta = job.get('meta') or {}
    selection = (meta.get('h3_recipe') or {}).get('source_selection')
    if selection is None:
        return None
    digest = selection.get('original_sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('The original soundtrack identity is unavailable.')
    source = _source(Path(meta.get('h3_original_source', '')), root / 'media')
    with _open_file(source) as stream:
        measured = hashlib.file_digest(stream, 'sha256').hexdigest()
    if measured != digest or expected_hash is not None and measured != expected_hash:
        raise ValueError('The original soundtrack no longer matches its saved source.')
    return source, selection


def _track_clock(source):
    result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file',
        '-show_entries', 'stream=codec_type,start_time,duration', '-of', 'json', str(source)],
        check=True, capture_output=True, timeout=30)
    streams = json.loads(result.stdout)['streams']
    audio = next((s for s in streams if s['codec_type'] == 'audio'), None)
    if audio is None:
        return None
    video = next(s for s in streams if s['codec_type'] == 'video')
    try:
        duration = Fraction(audio['duration'])
        delta = Fraction(video.get('start_time', '0')) - Fraction(audio.get('start_time', '0'))
    except (ValueError, KeyError, ZeroDivisionError):
        raise ValueError('The original soundtrack timing could not be measured.') from None
    if duration <= 0:
        raise ValueError('The original soundtrack is empty.')
    return duration, delta


def source_for_family(work, family):
    """Resolve once per request; return ephemeral clocks, never public file paths.

    Original music is available for explicitly selected excerpts of a retained
    long Swap source. Source-less roots keep native generated audio. We do not
    reconstruct missing old ancestry or pretend a short upload contains a sequel.
    """
    manifest = family.record.to_manifest()
    evidence = _read_json(family.mctx.parent / 'capture.private.json')
    graph = evidence['captured_graph']
    graph = json.loads(graph) if isinstance(graph, str) else graph
    metadata = graph.get('1216', {}).get('inputs', {}).get('metadata', '') if isinstance(graph, dict) else ''
    frozen = json.loads(metadata).get(METADATA_KEY) if isinstance(metadata, str) and metadata else None
    origin = manifest['origin']
    if frozen is not None:
        frozen = validate_audio_context(frozen)
        job_id, expected = frozen['source_job'], frozen['source_sha256']
    elif origin.get('operator_label') == 'native-swap':
        job_id, expected = origin['source_job'], None
    else:
        return None
    if not isinstance(job_id, str) or not re.fullmatch(r'[0-9a-f]{32}', job_id):
        raise ValueError('The original soundtrack origin is invalid.')
    resolved = _source_file(work, job_id, expected)
    if resolved is None:
        if frozen is not None:
            raise ValueError('The retained original soundtrack is unavailable.')
        return None
    source, selection = resolved
    clock = _track_clock(source)
    if clock is None:
        if frozen is not None:
            raise ValueError('The retained original soundtrack is missing.')
        return None
    return {'source_job': job_id, 'source_sha256': selection['original_sha256'],
            'raw_video_start': Fraction(frozen['raw_video_start'] if frozen else str(selection['start_seconds'])),
            'duration': clock[0], 'stream_delta': clock[1]}


def plan_source_audio(source, state, raw_frames):
    if source is None:
        return None
    window = audio_window(state, raw_frames, source['raw_video_start'])
    window['start_sample'] += round(source['stream_delta'] * RATE)
    require_audio_capacity(window, source['duration'])
    return validate_audio_context({'policy': POLICY, 'source_job': source['source_job'],
        'source_sha256': source['source_sha256'], **window})


def precheck_source_audio(work, context):
    """Same real decode/count guard for every caller, before client/refinement."""
    if context is not None:
        try:
            with tempfile.TemporaryDirectory(prefix='check-source-song-') as folder:
                prepare_source_audio(work, context, Path(folder) / 'source-song.wav')
        except (OSError, subprocess.SubprocessError):
            raise ValueError('The original soundtrack could not be decoded. Nothing was submitted.') from None


def prepare_source_audio(work, context, destination):
    context = validate_audio_context(context)
    resolved = _source_file(work, context['source_job'], context['source_sha256'])
    if resolved is None:
        raise ValueError('The retained original soundtrack is unavailable.')
    extract_audio_window(resolved[0], destination, context)
    return Path(destination)
