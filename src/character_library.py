"""Explicit Character library membership, independent of durable jobs and media.

One advisory process lock covers read/modify/replace. The index is never rebuilt from
jobs: a damaged index fails closed so a subsequent Keep cannot erase previous saves.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

import core
from character_capsule import contained, digest_file, get_capsule
from character_pipeline import _validate_png
from character_recipe import ENGINE

JOB_ID = re.compile(r"[0-9a-f]{32}\Z")


class LibraryError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def validate_id(job_id):
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise LibraryError(404, "Character job not found")


def _name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 100
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise LibraryError(422, "Character name must be 1–100 characters without control characters")
    return value.strip()


class CharacterLibrary:
    def __init__(self, get_media_dir):
        self.get_media_dir = get_media_dir

    @property
    def directory(self):
        return Path(core.WORK) / "characters"

    @contextmanager
    def _locked(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / "library.lock").open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError as exc:
            raise LibraryError(503, "Character library storage is unavailable") from exc

    def _read(self):
        path = self.directory / "library.json"
        try:
            with path.open(encoding="utf-8") as stream:
                data = json.load(stream)
        except FileNotFoundError:
            return []
        except (ValueError, UnicodeError) as exc:
            raise LibraryError(503, "Character library index is damaged; restore it before making changes") from exc
        try:
            if not isinstance(data, dict) or set(data) != {"version", "characters"} or type(data["version"]) is not int or data["version"] != 1:
                raise ValueError
            entries = data["characters"]
            if not isinstance(entries, list):
                raise ValueError
            seen = set()
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {"job_id", "name", "saved_at"}:
                    raise ValueError
                validate_id(entry["job_id"])
                if entry["job_id"] in seen or _name(entry["name"]) != entry["name"]:
                    raise ValueError
                timestamp = entry["saved_at"]
                if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp <= 0:
                    raise ValueError
                seen.add(entry["job_id"])
            return entries
        except (KeyError, ValueError, TypeError, LibraryError) as exc:
            raise LibraryError(503, "Character library index is damaged; restore it before making changes") from exc

    def _write(self, entries):
        target = self.directory / "library.json"
        temporary = self.directory / f"library.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump({"version": 1, "characters": entries}, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _public(entries):
        return [{**entry, "image_url": f"/api/characters/jobs/{entry['job_id']}/image"}
                for entry in sorted(entries, key=lambda item: (item["saved_at"], item["job_id"]), reverse=True)]

    def list(self):
        with self._locked():
            return self._public(self._read())

    def _completed(self, job_id):
        validate_id(job_id)
        try:
            job = core.Job.load(job_id)
        except KeyError as exc:
            raise LibraryError(404, "Character job not found") from exc
        except (OSError, ValueError, TypeError) as exc:
            raise LibraryError(409, "Character job record is unavailable") from exc
        if job.engine != ENGINE or job.id != job_id:
            raise LibraryError(404, "Character job not found")
        if not isinstance(job.meta, dict):
            raise LibraryError(409, "Character job record is unavailable")
        # Each refusal names the one thing that failed: "it did not work" is not a diagnosis.
        try:
            capsule = get_capsule(job)  # Historical capsules remain saveable; replay policy is separate.
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise LibraryError(409, "This job has no finished character capsule yet. Wait for it to complete, then save again.") from exc
        try:
            image = contained(job.result or "", self.get_media_dir())
        except (OSError, ValueError) as exc:
            raise LibraryError(409, "The generated image is missing or outside the studio library.") from exc
        try:
            caption = contained(job.meta.get("character_caption", ""), self.get_media_dir())
        except (OSError, ValueError) as exc:
            raise LibraryError(409, "The character caption file is missing from the studio library.") from exc
        for path, role, label in ((image, "image", "generated image"), (caption, "caption", "caption file")):
            try:
                expected = capsule["assets"][role]
                intact = (path.suffix.lower() == expected["suffix"]
                          and path.stat().st_size == expected["size_bytes"]
                          and digest_file(path) == expected["sha256"])
            except (OSError, KeyError, TypeError) as exc:
                raise LibraryError(409, f"The {label} cannot be read back for verification.") from exc
            if not intact:
                raise LibraryError(409, f"The {label} changed on disk since the job finished. Regenerate it to save this character.")
        try:
            _validate_png(image, capsule["recipe"]["mode"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LibraryError(409, "The generated image is not a valid PNG for this character mode.") from exc
        try:
            empty = not caption.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise LibraryError(409, "The caption file is unreadable.") from exc
        if empty:
            raise LibraryError(409, "The character caption is empty. Regenerate the character, then save it.")

    def save(self, job_id, payload):
        validate_id(job_id)
        if not isinstance(payload, dict) or set(payload) - {"name"}:
            raise LibraryError(422, "Character save accepts only an optional name")
        name = _name(payload["name"]) if "name" in payload else None
        self._completed(job_id)
        with self._locked():
            entries = self._read()
            existing = next((entry for entry in entries if entry["job_id"] == job_id), None)
            if existing is not None:
                if name is not None:
                    existing["name"] = name
            else:
                entries.append({"job_id": job_id, "name": name or "Untitled character", "saved_at": time.time()})
            self._write(entries)
        return {"job_id": job_id}

    def remove(self, job_id):
        validate_id(job_id)
        with self._locked():
            entries = self._read()
            self._write([entry for entry in entries if entry["job_id"] != job_id])
        return {"job_id": job_id}
