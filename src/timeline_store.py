"""Local single-process timeline persistence, immutable takes and optimistic edits.

Only this module knows private media paths. Public projections are allowlists.
Locks are shared by all store instances for the same resolved workspace.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from fractions import Fraction

from media_probe import probe_mp4
from timeline_models import CreateProject, EditNativeWorkspace, EditProject, MAX_CLIPS, MAX_KNOWN_CLIPS, ProjectAssets, AssociateAsset

_ID = re.compile(r"[0-9a-f]{32}\Z")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
MP4_INPUT = ["-protocol_whitelist", "file", "-f", "mov", "-enable_drefs", "0", "-use_absolute_path", "0"]


class TimelineError(ValueError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def identifier(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise TimelineError(422, "Invalid timeline identifier")
    return value


def check_revision(value: int, expected: int) -> None:
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise TimelineError(422, "Revision must be a nonnegative integer")
    if value != expected:
        raise TimelineError(409, "Timeline revision conflict; reload the project")


def atomic_json(path: Path, value: dict) -> None:
    """Same-filesystem replace, including flush before publication."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4_000_000:
                raise ValueError("Invalid manifest")
            value = json.load(stream)
            if not isinstance(value, dict):
                raise ValueError("Invalid manifest")
            return value
    except FileNotFoundError as exc:
        raise TimelineError(404, "Timeline record not found") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise TimelineError(409, "Timeline record cannot be read") from exc


def fingerprint(info) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def digest_file(path: Path) -> tuple[str, int, tuple[int, ...]]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not info.st_size:
                raise ValueError("Not a nonempty regular file")
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            before = fingerprint(info)
            if before != fingerprint(os.fstat(stream.fileno())) or before != fingerprint(path.stat()):
                raise ValueError("File changed")
        return digest.hexdigest(), info.st_size, before
    except (OSError, ValueError) as exc:
        raise TimelineError(409, "Timeline media is missing or changed") from exc


def inspect_mp4(path: Path) -> dict:
    """Decode a strictly local MOV container; never autodetect playlists."""
    try:
        media = probe_mp4(path)
        if (not 0 < media["width"] <= 8192 or not 0 < media["height"] <= 8192
                or media["width"] * media["height"] > 33_554_432
                or not 0 < media["frames"] <= 1_000_000
                or not math.isfinite(media["fps"]) or not 0 < media["fps"] <= 240
                or media["frames"] / media["fps"] > 21600):
            raise ValueError("Unsupported video geometry")
        result = subprocess.run(
            ["ffprobe", "-v", "error", *MP4_INPUT, "-show_frames", "-show_entries",
             "frame=media_type,best_effort_timestamp:stream=codec_type,avg_frame_rate,r_frame_rate,time_base", "-of", "json", str(path)],
            capture_output=True, text=True, check=True, timeout=180)
        data = json.loads(result.stdout)
        streams = data["streams"]
        video = next(s for s in streams if s["codec_type"] == "video")
        rate = Fraction(video["avg_frame_rate"])
        if rate != Fraction(video["r_frame_rate"]):
            raise ValueError("Variable frame rate is unsupported")
        ticks = Fraction(video["time_base"])
        points = [int(f["best_effort_timestamp"]) for f in data["frames"] if f["media_type"] == "video"]
        if len(points) != media["frames"] or ticks <= 0 or any(
                abs((point - points[0]) * ticks - Fraction(index, 1) / rate) > ticks
                for index, point in enumerate(points)):
            raise ValueError("Variable or unsupported frame timestamps")
        if sum(s["codec_type"] == "audio" for s in streams) > 1:
            raise ValueError("Multiple audio tracks need an explicit track-selection UI")
        # count_frames alone may tolerate truncated packets. Decode with fatal errors.
        subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-threads", "1", *MP4_INPUT,
                        "-i", str(path), "-map", "0:v:0", "-map", "0:a:0?",
                        "-f", "null", "-"], capture_output=True, check=True, timeout=180)
        return {"width": media["width"], "height": media["height"], "fps": media["fps"],
                "frames": media["frames"], "fps_ratio": str(rate),
                "video_start": str(points[0] * ticks),
                "has_audio": any(s["codec_type"] == "audio" for s in streams)}
    except Exception as exc:
        raise TimelineError(422, "Invalid, unsupported, or undecodable constant-rate MP4") from exc


class TimelineStore:
    def __init__(self, work_dir: Path, media_dir: Path, max_upload_bytes: int):
        if type(max_upload_bytes) is not int or max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be a positive integer")
        self.work = Path(work_dir).resolve()
        self.media = Path(media_dir).resolve()
        self.root = self.work / "timeline"
        self.max_upload_bytes = max_upload_bytes
        for directory in (self.root, self.root / "projects", self.root / "takes", self.root / "staging", self.root / "exports"):
            if directory.is_symlink():
                raise TimelineError(409, "Timeline storage must not be a symlink")
            directory.mkdir(parents=True, exist_ok=True)
        with _LOCKS_GUARD:
            self.lock = _LOCKS.setdefault(str(self.root), threading.RLock())

    def _path(self, group: str, record_id: str, filename: str | None = None) -> Path:
        parent = self.root / group
        path = parent / identifier(record_id)
        if filename:
            path = path / filename
        else:
            path = path.with_suffix(".json")
        # Private directory trees cannot redirect reads outside the timeline.
        if not path.resolve().is_relative_to(parent) or any(p.is_symlink() for p in (parent, path.parent, path)):
            raise TimelineError(409, "Timeline storage is unavailable")
        return path

    def _project(self, project_id: str) -> dict:
        return read_json(self._path("projects", project_id))

    def _job(self, job_id: str):
        identifier(job_id)
        import core
        try:
            # In the integrated app these roots match. The explicit-root fallback
            # supports embedded stores without ever changing core.WORK globally.
            if Path(core.WORK).resolve() == self.work:
                job = core.Job.load(job_id)
            else:
                job = core.Job(**read_json(self.work / "jobs" / f"{job_id}.json"))
            if job.id != job_id:
                raise ValueError("Mismatched job")
            return job
        except Exception as exc:
            raise TimelineError(404, "Source job not found") from exc

    def create(self, title: str, character_id: str | None = None, *, is_draft: bool = False) -> dict:
        data = CreateProject(title=title, character_id=character_id)
        if data.character_id:
            job = self._job(data.character_id)
            if job.engine != "flux3-klein-character" or job.status != "done" or not job.result:
                raise TimelineError(422, "Character context must be a completed Character job")
        now = time.time()
        project = {"project_id": uuid.uuid4().hex, "title": data.title, "revision": 0,
                   "created_at": now, "updated_at": now, "character_id": data.character_id,
                   "known_clips": {}, "clips": [], "is_draft": is_draft}
        with self.lock:
            atomic_json(self._path("projects", project["project_id"]), project)
            return self._public(project)

    def draft(self, *, create: bool = False) -> dict | None:
        """One reusable draft; a read never creates a project."""
        with self.lock:
            rows = [read_json(p) for p in (self.root / 'projects').glob('*.json') if _ID.fullmatch(p.stem)]
            drafts = [p for p in rows if p.get('is_draft') is True]
            if len(drafts) > 1:
                raise TimelineError(409, 'Multiple draft workspaces need reconciliation')
            if drafts:
                return self._public(drafts[0])
            return self.create('Draft', is_draft=True) if create else None

    def rename(self, project_id: str, revision: int, title: str) -> dict:
        with self.lock:
            project = self._project(project_id)
            check_revision(revision, project['revision'])
            project['title'] = CreateProject(title=title).title
            project['is_draft'] = False
            return self._save_edit(project)

    def _memberships(self, project: dict) -> dict:
        # Legacy ownership is projected without migrating or rewriting on GET.
        try:
            assets = ProjectAssets.model_validate(project.get('assets', {})).model_dump()
            if project.get('character_id'):
                assets['characters'].append(project['character_id'])
            assets['takes'].extend(p['take_id'] for p in project.get('native_workspace', {}).get('placements', []))
            for path in (self.work / 'jobs').glob('*.json'):
                if not _ID.fullmatch(path.stem) or path.is_symlink():
                    continue
                try:
                    job = read_json(path)
                except TimelineError:
                    continue
                meta = job.get('meta')
                if job.get('id') != path.stem or not isinstance(meta, dict) or meta.get('origin_project_id') != project['project_id']:
                    continue
                group = 'characters' if job.get('engine') == 'flux3-klein-character' else 'jobs'
                if job.get('engine') in ('flux3-klein-character', 'minimax-h3', 'ltx25-ripple'):
                    assets[group].append(job['id'])
            from continuity_attempts import _records, AttemptError
            try:
                attempts = _records(self.work / 'native-attempts')
            except (AttemptError, OSError):
                attempts = []
            for attempt in attempts:
                if attempt.get('project_id') == project['project_id']:
                    assets['takes'].extend(c['take_id'] for c in attempt['candidates'] if c.get('take_id'))
            assets = {key: list(dict.fromkeys(values)) for key, values in assets.items()}
            return ProjectAssets.model_validate(assets).model_dump()
        except (ValueError, KeyError, TypeError) as exc:
            raise TimelineError(409, 'Project membership cannot be read') from exc

    def get_assets(self, project_id: str) -> dict:
        with self.lock:
            project = self._project(project_id)
            assets = self._memberships(project)
            return {'project_id': project['project_id'], 'revision': project['revision'],
                    'assets': assets, 'jobs': self._project_job_summaries(assets)}

    def library_jobs(self) -> list[dict]:
        """Safe library projection over existing job files; no separate index."""
        rows = []
        for path in (self.work / 'jobs').glob('*.json'):
            if not _ID.fullmatch(path.stem) or path.is_symlink():
                continue
            try:
                job = self._job(path.stem)
            except TimelineError:
                continue
            if job.engine not in ('flux3-klein-character', 'minimax-h3', 'ltx25-ripple') or job.status != 'done':
                continue
            rows.append({'job_id': job.id, 'engine': job.engine, 'status': job.status,
                         'created': job.created})
        return sorted(rows, key=lambda row: row['created'], reverse=True)

    def _project_job_summaries(self, assets: dict) -> list[dict]:
        rows = []
        for job_id in assets['jobs'] + assets['characters']:
            try:
                job = self._job(job_id)
                rows.append({'job_id': job.id, 'engine': job.engine, 'status': job.status,
                             'created': job.created})
            except TimelineError:
                continue  # Membership survives an unavailable historical resource.
        return sorted(rows, key=lambda row: row['created'], reverse=True)

    def associate_asset(self, project_id: str, data: AssociateAsset) -> dict:
        with self.lock:
            project = self._project(project_id)
            check_revision(data.revision, project['revision'])
            assets = self._memberships(project)
            group = {'character': 'characters', 'job': 'jobs', 'take': 'takes'}[data.kind]
            if data.asset_id in assets[group]:
                return self.get_assets(project_id)
            if data.kind == 'take':
                import continuable_take
                try:
                    continuable_take.get_take(self.work, data.asset_id)
                except FileNotFoundError as exc:
                    raise TimelineError(404, 'Native Take not found') from exc
                except ValueError as exc:
                    raise TimelineError(422, 'Native Take metadata cannot be read') from exc
            else:
                job = self._job(data.asset_id)
                if data.kind == 'character':
                    valid = job.engine == 'flux3-klein-character' and job.status == 'done' and bool(job.result)
                else:
                    valid = job.engine in ('minimax-h3', 'ltx25-ripple')
                if not valid:
                    raise TimelineError(422, 'The resource does not have the requested project role')
            if len(assets[group]) >= MAX_KNOWN_CLIPS:
                raise TimelineError(422, 'This project resource list is full')
            assets[group].append(data.asset_id)
            project['assets'] = assets
            self._save_edit(project, native=True)
            return self.get_assets(project_id)

    def list_projects(self) -> list[dict]:
        with self.lock:
            projects = [read_json(p) for p in (self.root / "projects").glob("*.json") if _ID.fullmatch(p.stem)]
            result = []
            for project in sorted(projects, key=lambda p: p["updated_at"], reverse=True):
                native_count = len(project.get("native_workspace", {}).get("placements", []))
                legacy_count = len(project["clips"])
                kind = ("mixed" if legacy_count else "native") if native_count else ("legacy" if legacy_count else "empty")
                result.append({**{k: project[k] for k in ("project_id", "title", "revision", "updated_at")},
                               "native_placement_count": native_count, "legacy_clip_count": legacy_count,
                               "workspace_kind": kind})
            return result

    def _public(self, project: dict) -> dict:
        result = {k: project[k] for k in ("project_id", "title", "revision", "created_at", "updated_at", "character_id")}
        clips = []
        for placement in project["clips"]:
            known = project["known_clips"][placement["clip_id"]]
            take = read_json(self._path("takes", known["take_id"], "take.json"))
            clips.append({**{k: known[k] for k in ("clip_id", "take_id", "label", "engine", "source_job_id")},
                          **{k: take[k] for k in ("width", "height", "fps", "frames")},
                          "in_frame": placement["in_frame"], "out_frame": placement["out_frame"],
                          "media_url": f"/api/timeline/takes/{known['take_id']}/media"})
        result["is_draft"] = project.get("is_draft", False)
        result["clips"] = clips
        return result

    def get(self, project_id: str) -> dict:
        with self.lock:
            return self._public(self._project(project_id))

    def _native_public(self, project: dict) -> dict:
        """Path-free rail projection; reading a legacy project never migrates it."""
        workspace = project.get("native_workspace", {})
        return {**{k: project[k] for k in ("project_id", "title", "revision", "updated_at")},
                "placements": workspace.get("placements", []),
                "selected_placement_id": workspace.get("selected_placement_id"),
                "drafts": workspace.get("drafts", {}),
                **{k: workspace[k] for k in ('selected_position', 'position_drafts') if k in workspace}}

    def get_native_workspace(self, project_id: str) -> dict:
        with self.lock:
            return self._native_public(self._project(project_id))

    def edit_native_workspace(self, project_id: str, edit: EditNativeWorkspace) -> dict:
        import continuable_take
        with self.lock:
            project = self._project(project_id)
            check_revision(edit.revision, project["revision"])
            for take_id in dict.fromkeys(p.take_id for p in edit.placements):
                try:
                    # Only read frozen metadata, not media integrity or ancestry.
                    continuable_take.get_take(self.work, take_id)
                except FileNotFoundError as exc:
                    raise TimelineError(404, "Native Take not found") from exc
                except ValueError as exc:
                    raise TimelineError(422, "Native Take metadata cannot be read") from exc
            assets = self._memberships(project)
            assets['takes'] = list(dict.fromkeys(assets['takes'] + [p.take_id for p in edit.placements]))
            if len(assets['takes']) > MAX_KNOWN_CLIPS:
                raise TimelineError(422, 'This project resource list is full')
            project['assets'] = assets
            prior = project.get('native_workspace', {})
            workspace = edit.model_dump(include={"placements", "selected_placement_id", "drafts"})
            for key in ('selected_position', 'position_drafts'):
                if key in edit.model_fields_set:
                    workspace[key] = edit.model_dump()[key]
                elif key in prior:
                    workspace[key] = prior[key]
            # An older client may reorder/remove anchors without sending the new
            # fields. Preserve its drafts, but do not retain an impossible selection.
            from timeline_models import position_is_current
            selected = workspace.get('selected_position')
            if selected and not position_is_current(selected, edit.placements):
                workspace['selected_position'] = None
            project["native_workspace"] = workspace
            if edit.title is not None:
                if edit.title != project["title"]:
                    project["is_draft"] = False
                project["title"] = edit.title
            return self._save_edit(project, native=True)

    def _save_edit(self, project: dict, *, native: bool = False) -> dict:
        project["revision"] += 1
        project["updated_at"] = time.time()
        atomic_json(self._path("projects", project["project_id"]), project)
        return self._native_public(project) if native else self._public(project)

    def edit(self, project_id: str, edit: EditProject) -> dict:
        with self.lock:
            project = self._project(project_id)
            check_revision(edit.revision, project["revision"])
            for clip in edit.clips:
                known = project["known_clips"].get(clip.clip_id)
                if not known:
                    raise TimelineError(422, "Clip has not been imported into this project")
                take = read_json(self._path("takes", known["take_id"], "take.json"))
                if clip.out_frame > take["frames"]:
                    raise TimelineError(422, "Frame range exceeds take length")
            project["clips"] = [c.model_dump() for c in edit.clips]
            if edit.title is not None:
                if edit.title != project["title"]:
                    project["is_draft"] = False
                project["title"] = edit.title
            return self._save_edit(project)

    def _source(self, source: Path, root: Path) -> Path:
        try:
            resolved = source.resolve(strict=True)
            if not resolved.is_relative_to(root) or resolved == root:
                raise ValueError("Outside media root")
            if source.is_symlink() or not stat.S_ISREG(resolved.stat().st_mode):
                raise ValueError("Not regular")
            return resolved
        except (OSError, ValueError, RuntimeError) as exc:
            raise TimelineError(422, "Source must be a regular file inside the allowed media root") from exc

    def import_job(self, project_id: str, revision: int, job_id: str) -> dict:
        job = self._job(job_id)
        if job.engine not in {"minimax-h3", "ltx25-ripple"} or job.status != "done" or not job.result:
            raise TimelineError(422, "Only completed H3 or LTX video jobs can be imported")
        source = Path(job.result)
        if not source.is_absolute():
            source = self.media / source if len(source.parts) == 1 else source.absolute()
        return self._import(project_id, revision, source, self.media, job.engine, job_id)

    def import_upload(self, project_id: str, revision: int, staged_path: Path) -> dict:
        return self._import(project_id, revision, staged_path, self.root / "staging", "upload", None)

    def _import(self, project_id: str, revision: int, source: Path, root: Path,
                engine: str, source_job_id: str | None) -> dict:
        # Validate and check revision before the expensive copy, then check again
        # at publication. Concurrent edits never get overwritten.
        with self.lock:
            check_revision(revision, self._project(project_id)["revision"])
        source = self._source(source, root)
        take_id, clip_id = uuid.uuid4().hex, uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="take-", dir=self.root / "staging") as staging:
            stage = Path(staging)
            destination = stage / "video.mp4"
            try:
                fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as incoming, destination.open("xb") as outgoing:
                    before = os.fstat(incoming.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise TimelineError(422, "Source must be a regular video file")
                    if before.st_size > self.max_upload_bytes:
                        raise TimelineError(413, "Video exceeds the configured upload limit")
                    total = 0
                    for block in iter(lambda: incoming.read(1024 * 1024), b""):
                        total += len(block)
                        if total > self.max_upload_bytes:
                            raise TimelineError(413, "Video exceeds the configured upload limit")
                        outgoing.write(block)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                    if fingerprint(before) != fingerprint(os.fstat(incoming.fileno())) or fingerprint(before) != fingerprint(source.stat()):
                        raise TimelineError(409, "Source changed during import")
            except OSError as exc:
                raise TimelineError(422, "Source cannot be read") from exc
            sha, size, identity = digest_file(destination)
            media = inspect_mp4(destination)
            if (sha, size, identity) != digest_file(destination):
                raise TimelineError(409, "Video changed during validation")
            take = {"take_id": take_id, **media, "sha256": sha, "size_bytes": size,
                    "identity": list(identity)}
            atomic_json(stage / "take.json", take)
            final = self.root / "takes" / take_id
            with self.lock:
                project = self._project(project_id)
                check_revision(revision, project["revision"])
                if len(project["clips"]) >= MAX_CLIPS or len(project["known_clips"]) >= MAX_KNOWN_CLIPS:
                    raise TimelineError(422, "Project clip limit reached")
                stage.rename(final)
                # Renaming the parent directory preserves the video's inode and
                # timestamps. The complete manifest is published with its media.
                label = f"{engine} take" if source_job_id else "Imported video"
                project["known_clips"][clip_id] = {"clip_id": clip_id, "take_id": take_id,
                    "engine": engine, "source_job_id": source_job_id, "label": label}
                project["clips"].append({"clip_id": clip_id, "in_frame": 0, "out_frame": media["frames"]})
                return self._save_edit(project)

    def take_media(self, take_id: str) -> Path:
        with self.lock:
            take = read_json(self._path("takes", take_id, "take.json"))
            path = self._path("takes", take_id, "video.mp4")
            sha, size, identity = digest_file(path)
            if sha != take["sha256"] or size != take["size_bytes"] or list(identity) != take["identity"]:
                raise TimelineError(409, "Timeline media is missing or changed")
            return path

    def _native_family(self, take_id: str, capsule_sha256: str | None = None):
        from continuable_take import get_validated_family
        identifier(take_id)
        try:
            family = get_validated_family(self.work, take_id)
        except FileNotFoundError as exc:
            raise TimelineError(409, "Native Take files are missing or changed") from exc
        except (ValueError, OSError) as exc:
            raise TimelineError(409, "Native Take files are missing or changed") from exc
        if capsule_sha256 is not None and family.record.capsule_sha256 != capsule_sha256:
            raise TimelineError(409, "Snapshot native state changed")
        return family

    def native_take_media(self, take_id: str, capsule_sha256: str) -> Path:
        """Recheck the complete sealed family, not only its visible derivative."""
        return self._native_family(take_id, capsule_sha256).video

    def native_snapshot(self, project_id: str, revision: int) -> dict:
        """Freeze the persisted native path; no legacy projection or project write.

        Decoding does not hold the project lock. A late revision check rejects
        edits made during validation before any export can be queued.
        """
        with self.lock:
            project = self._project(project_id)
            check_revision(revision, project["revision"])
            placements = [dict(p) for p in project.get("native_workspace", {}).get("placements", [])]
            frozen = {k: project[k] for k in ("project_id", "title", "revision")}
        if not placements:
            raise TimelineError(422, "Add a take to the sequence before exporting")
        assets, segments = {}, []
        for placement in placements:
            take_id = placement["take_id"]
            if take_id not in assets:
                family = self._native_family(take_id)
                capsule = family.record.capsule_sha256
                context = family.record.to_manifest()["family"]["context"]
                before = digest_file(family.video)
                media = inspect_mp4(family.video)
                if (media["width"], media["height"], media["frames"]) != (
                        context["width"], context["height"], context["delivered_frames"]) or (
                        Fraction(media["fps_ratio"]) != Fraction(str(context["fps"]))):
                    raise TimelineError(409, "Native video differs from its saved state")
                path = self.native_take_media(take_id, capsule)
                if path != family.video or digest_file(path) != before:
                    raise TimelineError(409, "Native video changed during validation")
                assets[take_id] = {**media, "sha256": before[0], "size_bytes": before[1],
                                   "identity": list(before[2]), "capsule_sha256": capsule}
            media = assets[take_id]
            segments.append({**placement, "in_frame": 0, "out_frame": media["frames"],
                             **{k: media[k] for k in ("width", "height", "fps")}})
        rates = {a["fps_ratio"] for a in assets.values()}
        if len(rates) != 1:
            raise TimelineError(409, "Mixed frame rates are unsupported; no silent FPS conversion")
        rate = Fraction(next(iter(rates)))
        if sum(s["out_frame"] for s in segments) / rate > 1200:
            raise TimelineError(422, "Export is limited to 20 minutes")
        with self.lock:
            check_revision(revision, self._project(project_id)["revision"])
        return {"source": "native", "project": frozen, "segments": segments, "assets": assets}

    def snapshot(self, project_id: str, revision: int) -> dict:
        with self.lock:
            project = self._project(project_id)
            check_revision(revision, project["revision"])
            public = self._public(project)
            if not public["clips"]:
                raise TimelineError(422, "Add a clip before exporting")
            assets = {}
            for clip in public["clips"]:
                self.take_media(clip["take_id"])
                assets[clip["take_id"]] = read_json(self._path("takes", clip["take_id"], "take.json"))
            rates = {a["fps_ratio"] for a in assets.values()}
            if len(rates) != 1:
                raise TimelineError(409, "Mixed frame rates are unsupported; no silent FPS conversion")
            if sum(c["out_frame"] - c["in_frame"] for c in public["clips"]) / public["clips"][0]["fps"] > 1200:
                raise TimelineError(422, "Export is limited to 20 minutes")
            return {"project": public, "assets": assets}
