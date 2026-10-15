"""Bounded upload storage; media probing runs outside the ASGI event loop."""
import asyncio
from pathlib import Path
from fastapi import HTTPException, UploadFile
import core


async def save_video(video: UploadFile, destination: Path, limit: int):
    total = 0
    try:
        with destination.open("wb") as out:
            while chunk := await video.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, f"Video exceeds the {limit} byte upload limit.")
                out.write(chunk)
        if total == 0:
            raise HTTPException(400, "The video file is empty.")
        return await asyncio.to_thread(core.ffprobe, destination)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "Unreadable video. Check the file format and video stream.") from exc
    finally:
        await video.close()
