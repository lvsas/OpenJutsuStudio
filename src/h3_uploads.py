"""Bounded, decoded and sanitized H3 image uploads without optional imaging deps."""
import asyncio
import json
import subprocess
from fastapi import HTTPException
from h3_media import ffmpeg

MAX_REFERENCE_BYTES = 20 * 1024 * 1024


def sanitize_reference(raw, destination):
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=codec_name,width,height', '-of', 'json', str(raw)],
        capture_output=True, text=True, check=True, timeout=30)
    streams = json.loads(probe.stdout).get('streams', [])
    if not streams:
        raise ValueError('No image stream')
    info = streams[0]
    width, height = info['width'], info['height']
    if (info['codec_name'] not in {'png', 'mjpeg', 'webp'} or min(width, height) < 32
            or max(width, height) > 8192 or width * height > 16_777_216):
        raise ValueError('Reference must be a PNG/JPEG/WebP, 32–8192 pixels per side, at most 16 megapixels')
    ffmpeg('-i', raw, '-map', '0:v:0', '-frames:v', 1, '-map_metadata', -1,
           '-threads', 1, destination)


async def save_reference(upload, destination, limit):
    raw = destination.with_suffix('.upload')
    try:
        total = 0
        with raw.open('wb') as stream:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > min(limit, MAX_REFERENCE_BYTES):
                    raise HTTPException(413, 'H3 reference exceeds the upload byte limit')
                stream.write(chunk)
        if not total:
            raise HTTPException(422, 'H3 requires a nonempty image reference')
        await asyncio.to_thread(sanitize_reference, raw, destination)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, 'Invalid reference: use a decodable PNG/JPEG/WebP, 32–8192 pixels per side, at most 16 megapixels') from exc
    finally:
        raw.unlink(missing_ok=True)
        await upload.close()
