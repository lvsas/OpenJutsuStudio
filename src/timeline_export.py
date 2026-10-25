"""Bounded CPU export queue with persistent immutable revision snapshots.

No GPU clients or subprocess shells. Each invocation decodes strict local MOV
inputs, trims exact frames, pads to the first clip canvas, and retains audio.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import uuid

from media_probe import probe_mp4
from timeline_store import (MP4_INPUT, TimelineError, TimelineStore, atomic_json,
                            digest_file, identifier, read_json, check_revision)
from timeline_swap_sources import placement_asset_key, swap_source

MAX_INTERMEDIATE_BYTES = 4 * 1024**3


def _ffmpeg(arguments: list[str], timeout: float) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-xerror", "-nostdin", "-threads", "1",
                    "-filter_threads", "1", *arguments],
                   capture_output=True, check=True, timeout=timeout)


def _display_fit(width: int, height: int) -> str:
    """Fit display geometry, not encoded pixels, without a huge SAR intermediate.

    Normalize sample aspect into the bounded target dimensions before setsar=1.
    Round to even pixel dimensions; both bounds are even, so rounding cannot
    escape the canvas. Missing/unspecified source SAR is treated as square.
    """
    aspect = "(iw/ih*if(gt(sar,0),sar,1))"
    return (f"scale=w='max(2,round(min({width},{height}*{aspect})/2)*2)':"
            f"h='max(2,round(min({height},{width}/{aspect})/2)*2)',"
            f"setsar=1,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p")


def render_snapshot(store: TimelineStore, snapshot: dict, output: Path, timeout: int = 600) -> None:
    """Sequential lossless intermediates keep decoder use independent of clip count."""
    native = snapshot.get("source") == "native"
    clips = snapshot["segments"] if native else snapshot["project"]["clips"]
    assets = snapshot["assets"]

    def source_media(key):
        take = assets[key]
        if native and take.get('source_kind') == 'swap':
            return swap_source(store, take['job_id'], take)[0]
        return (store.native_take_media(key, take["capsule_sha256"])
                if native else store.take_media(key))
    first = clips[0]
    # yuv420p requires even dimensions; round *up*, never crop an odd edge.
    width, height = (first["width"] + 1) // 2 * 2, (first["height"] + 1) // 2 * 2
    if width * height > 8_847_360:
        raise TimelineError(422, "Export canvas exceeds the supported pixel budget")
    rate = Fraction(assets[placement_asset_key(first)]["fps_ratio"])
    deadline = time.monotonic() + timeout

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("Export deadline exceeded")
        return seconds

    with tempfile.TemporaryDirectory(prefix="export-", dir=store.root / "staging") as temporary:
        staging = Path(temporary)
        total_bytes = 0
        entries = []
        for index, clip in enumerate(clips):
            key = placement_asset_key(clip)
            take = assets[key]
            path = source_media(key)
            # A snapshot is authoritative even if someone changes a take manifest.
            before = digest_file(path)
            if before[0] != take["sha256"] or before[1] != take["size_bytes"] or list(before[2]) != take["identity"]:
                raise TimelineError(409, "Snapshot media is missing or changed")
            count = clip["out_frame"] - clip["in_frame"]
            start_sample = round(Fraction(clip["in_frame"] * 48000, 1) / rate)
            sample_count = round(Fraction(count * 48000, 1) / rate)
            vf = (f"trim=start_frame={clip['in_frame']}:end_frame={clip['out_frame']},"
                  f"setpts=N/({rate}*TB),{_display_fit(width, height)}")
            inputs = ["-copyts", *MP4_INPUT, "-i", str(path)]
            audio_stream = "0:a:0"
            audio_origin = take["video_start"]
            if not take["has_audio"]:
                inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                audio_stream = "1:a:0"
                audio_origin = "0"
                start_sample = 0
            af = (f"asetpts=PTS-({audio_origin})/TB,aresample=48000:first_pts=0,"
                  f"aformat=sample_fmts=s16:channel_layouts=stereo,"
                  f"atrim=start_sample={start_sample},asetpts=PTS-STARTPTS,"
                  f"apad=whole_len={sample_count},atrim=end_sample={sample_count},asetpts=N/SR/TB")
            name = f"segment{index:04d}.nut"
            segment = staging / name
            _ffmpeg([*inputs, "-map", "0:v:0", "-map", audio_stream, "-vf", vf, "-af", af,
                     "-map_metadata", "-1", "-map_chapters", "-1",
                     "-fps_mode", "passthrough", "-c:v", "ffv1", "-level", "3", "-threads", "1",
                     "-c:a", "pcm_s16le", "-f", "nut", str(segment)], remaining())
            if digest_file(path) != before:
                raise TimelineError(409, "Snapshot media changed while exporting")
            total_bytes += segment.stat().st_size
            if total_bytes > MAX_INTERMEDIATE_BYTES:
                raise TimelineError(422, "Export exceeds the intermediate storage budget")
            entries.append(f"file '{name}'\nduration {float(Fraction(count, 1) / rate):.12f}\n")
        listing = staging / "segments.txt"
        listing.write_text("".join(entries), encoding="ascii")
        rendered = staging / "render.mp4"
        _ffmpeg(["-protocol_whitelist", "file", "-f", "concat", "-safe", "1", "-i", str(listing),
                 "-map", "0:v:0", "-map", "0:a:0", "-map_metadata", "-1", "-map_chapters", "-1",
                 "-fps_mode", "passthrough",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "1",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                 "-video_track_timescale", str(rate.numerator), "-movie_timescale", "48000",
                 "-movflags", "+faststart", str(rendered)], remaining())
        media = probe_mp4(rendered)
        expected = sum(c["out_frame"] - c["in_frame"] for c in clips)
        if media["frames"] != expected or (media["width"], media["height"]) != (width, height):
            raise TimelineError(409, "Export frame verification failed")
        # All inputs are checked again before publication, not only their own pass.
        for take_id, take in assets.items():
            path = source_media(take_id)
            actual = digest_file(path)
            if actual[0] != take["sha256"] or actual[1] != take['size_bytes'] or list(actual[2]) != take["identity"]:
                raise TimelineError(409, "Snapshot media changed while exporting")
        rendered.replace(output)


class _ExportQueue:
    """One shared queue per workspace/process; active + waiting capacity is bounded."""
    def __init__(self, store: TimelineStore, workers: int = 1, max_queued: int = 3, timeout: int = 600):
        if type(workers) is not int or not 1 <= workers <= 2 or type(max_queued) is not int or not 0 <= max_queued <= 16:
            raise ValueError("Invalid CPU export queue bounds")
        self.store = store
        self.timeout = timeout
        self._slots = threading.BoundedSemaphore(workers + max_queued)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="timeline-cpu")
        self._closed = False
        self._by_revision: dict[tuple[str, str, int], str] = {}
        self._terminal_failures: dict[str, dict] = {}
        with store.lock:
            for directory in (store.root / "exports").iterdir():
                if not directory.is_dir() or directory.is_symlink():
                    continue
                try:
                    identifier(directory.name)
                    state = self._state(directory.name)
                    if state["status"] in {"queued", "running"}:
                        state.update(status="error", error="Export interrupted by application restart")
                        atomic_json(self._path(directory.name, "status.json"), state)
                    if state["status"] != "error":
                        self._by_revision[(state.get("source", "legacy"), state["project_id"], state["revision"])] = directory.name
                except (TimelineError, KeyError):
                    continue

    def _path(self, export_id: str, name: str) -> Path:
        return self.store._path("exports", export_id, name)

    def _state(self, export_id: str) -> dict:
        # Callers hold store.lock. A finished worker's failure overrides stale
        # disk state until both orphan cleanup and terminal persistence succeed.
        state = self._terminal_failures.get(export_id)
        if state is not None:
            try:
                self._path(export_id, "video.mp4").unlink(missing_ok=True)
                atomic_json(self._path(export_id, "status.json"), state)
            except OSError:
                pass
            else:
                del self._terminal_failures[export_id]
            return state
        return read_json(self._path(export_id, "status.json"))

    @staticmethod
    def _public(state: dict) -> dict:
        result = {k: state[k] for k in ("export_id", "status", "project_id", "revision", "error")}
        base = f"/api/timeline/exports/{state['export_id']}"
        result["status_url"] = base
        result["preview_url"] = base + "/media" if state["status"] == "ready" else None
        result["download_url"] = base + "/media?download=true" if state["status"] == "ready" else None
        if state.get("source") == "native":
            result.update(source="native", placement_ids=list(state["placement_ids"]))
        return result

    def submit(self, project_id: str, revision: int, *, source: str = "legacy") -> dict:
        if source not in ("legacy", "native"):
            raise TimelineError(422, "Unknown export source")
        snapshot = (self.store.native_snapshot(project_id, revision) if source == "native"
                    else self.store.snapshot(project_id, revision))
        with self.store.lock:
            check_revision(revision, self.store._project(project_id)["revision"])
            key = (source, project_id, revision)
            if key in self._by_revision:
                previous = self.get(self._by_revision[key])
                if previous["status"] != "error":
                    return previous
            # Do not accumulate unpersisted terminal records during an outage:
            # only the already bounded active/waiting jobs may add failures.
            for failed_id in tuple(self._terminal_failures):
                self._state(failed_id)
            if self._terminal_failures:
                raise TimelineError(503, "Export storage is unavailable; try again later")
            if self._closed or not self._slots.acquire(blocking=False):
                raise TimelineError(503, "CPU export queue is full; try again later")
            export_id = uuid.uuid4().hex
            state = {"export_id": export_id, "status": "queued", "project_id": project_id,
                     "revision": revision, "error": None, "source": source}
            if source == "native":
                state["placement_ids"] = [s["placement_id"] for s in snapshot["segments"]]
            try:
                self._path(export_id, "status.json").parent.mkdir()
                atomic_json(self._path(export_id, "snapshot.json"), snapshot)
                atomic_json(self._path(export_id, "status.json"), state)
                self._by_revision[key] = export_id
                self._pool.submit(self._run, export_id)
            except Exception:
                self._slots.release()
                self._by_revision.pop(key, None)
                raise
            return self._public(state)

    def _run(self, export_id: str) -> None:
        try:
            with self.store.lock:
                state = self._state(export_id)
                state["status"] = "running"
                atomic_json(self._path(export_id, "status.json"), state)
                snapshot = read_json(self._path(export_id, "snapshot.json"))
            output = self._path(export_id, "video.mp4")
            render_snapshot(self.store, snapshot, output, self.timeout)
            sha, size, identity = digest_file(output)
            with self.store.lock:
                state.update(status="ready", error=None, sha256=sha, size_bytes=size, identity=list(identity))
                atomic_json(self._path(export_id, "status.json"), state)
        except Exception:
            # Never persist subprocess stderr, source paths, exception strings or argv.
            with self.store.lock:
                state = self._state(export_id)
                state.update(status="error", error="CPU export failed; check media integrity, limits, or FFmpeg availability")
                self._terminal_failures[export_id] = state
                self._state(export_id)
        finally:
            self._slots.release()

    def get(self, export_id: str) -> dict:
        with self.store.lock:
            return self._public(self._state(export_id))

    def media(self, export_id: str) -> Path:
        with self.store.lock:
            state = self._state(export_id)
            if state["status"] != "ready":
                raise TimelineError(409, "Export is not ready")
            path = self._path(export_id, "video.mp4")
            sha, size, identity = digest_file(path)
            if sha != state["sha256"] or size != state["size_bytes"] or list(identity) != state["identity"]:
                raise TimelineError(409, "Export media is missing or changed")
            return path

    def close(self) -> None:
        with self.store.lock:
            self._closed = True
        self._pool.shutdown(wait=True)


_QUEUES_GUARD = threading.RLock()
_QUEUES: dict[str, tuple[_ExportQueue, int]] = {}


class ExportManager:
    """Reference-counted access to the workspace's one CPU export queue.

    Multiple routers/stores in the same process share singleflight and capacity.
    The first live manager chooses queue limits. The last close drains workers.
    """
    def __init__(self, store: TimelineStore, workers: int = 1, max_queued: int = 3, timeout: int = 600):
        self._key = str(store.root)
        self._closed = False
        with _QUEUES_GUARD:
            existing = _QUEUES.get(self._key)
            if existing is None:
                self._queue = _ExportQueue(store, workers, max_queued, timeout)
                _QUEUES[self._key] = (self._queue, 1)
            else:
                self._queue, references = existing
                _QUEUES[self._key] = (self._queue, references + 1)

    def submit(self, project_id: str, revision: int, *, source: str = "legacy") -> dict:
        if self._closed:
            raise TimelineError(503, "CPU export queue is closed")
        return self._queue.submit(project_id, revision, source=source)

    def get(self, export_id: str) -> dict:
        return self._queue.get(export_id)

    def media(self, export_id: str) -> Path:
        return self._queue.media(export_id)

    def close(self) -> None:
        with _QUEUES_GUARD:
            if self._closed:
                return
            self._closed = True
            queue, references = _QUEUES[self._key]
            if references == 1:
                # Hold the registry guard through drain: a new manager must not
                # mistake this process's live renders for interrupted old jobs.
                queue.close()
                del _QUEUES[self._key]
            else:
                _QUEUES[self._key] = (queue, references - 1)
