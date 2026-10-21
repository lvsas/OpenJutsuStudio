"""All media and Job writes stay in a caller-owned TMPDIR fixture."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from timeline_models import EditProject
from timeline_store import TimelineStore, TimelineError


def make_video(path, color="black", frames=12, fps="12", size="64x48", audio=False):
    args = ["ffmpeg", "-y", "-v", "error", "-threads", "1", "-f", "lavfi", "-i",
            f"color=c={color}:s={size}:r={fps}"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000"]
    if not audio:
        args += ["-frames:v", str(frames)]
    args += ["-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-t", str(frames / float(__import__('fractions').Fraction(fps))) ]
    subprocess.run(args + [str(path)], check=True, capture_output=True, timeout=30)
    return path


class IsolatedTimeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"], prefix="timeline-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.media = self.work / "media"
        self.media.mkdir()
        env_patch = patch.dict(os.environ, {"OPENGENJUTSU_WORK": str(self.work)})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        import core
        self.job_patch = patch.object(core, "WORK", self.work)
        self.job_patch.start()
        self.addCleanup(self.job_patch.stop)
        self.store = TimelineStore(self.work, self.media, 2_000_000)

    def job(self, path, engine="minimax-h3", status="done"):
        from core import Job
        import uuid
        job = Job(id=uuid.uuid4().hex, result=str(path), engine=engine, status=status)
        job.save()
        return job

    def imported(self, **kwargs):
        path = make_video(self.media / (str(len(list(self.media.iterdir()))) + ".mp4"), **kwargs)
        project = self.store.create("Assembly")
        return self.store.import_job(project["project_id"], 0, self.job(path).id), path


class TimelineStoreTests(IsolatedTimeline):
    def test_empty_create_list_get_restart(self):
        project = self.store.create("First")
        self.assertEqual(project["clips"], [])
        self.assertIsNone(project["character_id"])
        self.assertEqual(project["revision"], 0)
        restarted = TimelineStore(self.work, self.media, 2_000_000)
        self.assertEqual(restarted.get(project["project_id"]), project)
        self.assertEqual(restarted.list_projects()[0]["project_id"], project["project_id"])
        with self.assertRaises(TimelineError):
            self.store.get("../jobs")

    def test_copied_take_trim_remove_undo_and_conflict(self):
        project, source = self.imported()
        source_bytes = source.read_bytes()
        clip = project["clips"][0]
        self.assertEqual(clip["frames"], 12)
        take = self.store.take_media(clip["take_id"])
        source.write_bytes(b"changed source")
        self.assertEqual(take.read_bytes(), source_bytes)
        edit = EditProject(revision=1, clips=[{"clip_id": clip["clip_id"], "in_frame": 2, "out_frame": 8}])
        project = self.store.edit(project["project_id"], edit)
        self.assertEqual(project["clips"][0]["out_frame"], 8)
        with self.assertRaises(TimelineError) as error:
            self.store.edit(project["project_id"], edit)
        self.assertEqual(error.exception.status_code, 409)
        project = self.store.edit(project["project_id"], EditProject(revision=2, clips=[]))
        self.assertEqual(project["clips"], [])
        self.store = TimelineStore(self.work, self.media, 2_000_000)
        project = self.store.edit(project["project_id"], EditProject(revision=3, clips=edit.clips))
        self.assertEqual(project["clips"][0]["take_id"], clip["take_id"])
        self.assertEqual(len(list((self.work / "timeline" / "takes").iterdir())), 1)
        self.assertNotIn(str(self.work), str(project))

    def test_job_media_and_character_validation(self):
        path = make_video(self.media / "good.mp4")
        project = self.store.create("x")
        for engine, status in (("flux3-klein-character", "done"), ("minimax-h3", "running"), ("unknown", "done")):
            with self.subTest(engine=engine), self.assertRaises(TimelineError):
                self.store.import_job(project["project_id"], 0, self.job(path, engine, status).id)
        character = self.job(path, "flux3-klein-character")
        self.assertEqual(self.store.create("Context", character.id)["character_id"], character.id)
        with self.assertRaises(TimelineError):
            self.store.create("Not character", self.job(path).id)
        outside = make_video(self.work / "outside.mp4")
        for bad in (outside, self.media, self.media / "link.mp4"):
            if bad.name == "link.mp4":
                bad.symlink_to(outside)
            with self.subTest(path=bad), self.assertRaises(TimelineError):
                self.store.import_job(project["project_id"], 0, self.job(bad).id)
        playlist = self.media / "playlist.mp4"
        playlist.write_text("#EXTM3U\nhttp://127.0.0.1:1/secret\n")
        with self.assertRaises(TimelineError):
            self.store.import_job(project["project_id"], 0, self.job(playlist).id)

    def test_unknown_duplicate_and_out_of_bounds_clips(self):
        project, _ = self.imported()
        clip = project["clips"][0]
        for placement in ({"clip_id": "a" * 32, "in_frame": 0, "out_frame": 1},
                          {"clip_id": clip["clip_id"], "in_frame": 0, "out_frame": 13}):
            with self.assertRaises(TimelineError):
                self.store.edit(project["project_id"], EditProject(revision=1, clips=[placement]))
        with self.assertRaises(TimelineError):
            self.store.import_job(project["project_id"], True, clip["source_job_id"])

    def test_concurrent_stores_do_not_overwrite_revisions(self):
        from concurrent.futures import ThreadPoolExecutor
        project = self.store.create("Concurrent")
        other = TimelineStore(self.work, self.media, 2_000_000)
        def edit(store):
            try:
                return store.edit(project["project_id"], EditProject(revision=0, clips=[]))["revision"]
            except TimelineError as exc:
                return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(edit, (self.store, other)))
        self.assertEqual(sorted(results), [1, 409])
        self.assertEqual(self.store.get(project["project_id"])["revision"], 1)

    def test_nonregular_and_mutating_assets_are_rejected(self):
        fifo = self.media / "fifo.mp4"
        os.mkfifo(fifo)
        project = self.store.create("Sources")
        with self.assertRaises(TimelineError):
            self.store.import_job(project["project_id"], 0, self.job(fifo).id)
        source = make_video(self.media / "good.mp4")
        from timeline_store import inspect_mp4
        def mutating_probe(path):
            result = inspect_mp4(path)
            path.write_bytes(path.read_bytes() + b"changed")
            return result
        with patch("timeline_store.inspect_mp4", side_effect=mutating_probe):
            with self.assertRaises(TimelineError) as error:
                self.store.import_job(project["project_id"], 0, self.job(source).id)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.store.get(project["project_id"])["revision"], 0)
        self.assertEqual(list((self.work / "timeline" / "staging").iterdir()), [])
        self.assertEqual(list((self.work / "timeline" / "takes").iterdir()), [])

    def test_variable_rate_and_multiple_audio_tracks_are_explicitly_refused(self):
        variable = self.media / "variable.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x48:r=10",
                        "-vf", "setpts='if(lt(N,5),N,2*N-5)/(10*TB)'", "-fps_mode", "vfr",
                        "-frames:v", "10", "-c:v", "libx264", "-threads", "1", str(variable)],
                       capture_output=True, check=True, timeout=30)
        multiple = self.media / "tracks.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=s=64x48:r=10:d=1",
                        "-f", "lavfi", "-i", "sine=d=1", "-f", "lavfi", "-i", "sine=f=440:d=1",
                        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-threads", "1",
                        "-c:a", "aac", "-t", "1", str(multiple)], capture_output=True, check=True, timeout=30)
        project = self.store.create("Unsupported media")
        for path in (variable, multiple):
            with self.subTest(path=path), self.assertRaises(TimelineError) as error:
                self.store.import_job(project["project_id"], 0, self.job(path).id)
            self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(self.store.get(project["project_id"])["clips"], [])

    def test_changed_take_refused(self):
        project, _ = self.imported()
        take_id = project["clips"][0]["take_id"]
        path = self.store.take_media(take_id)
        path.write_bytes(b"corrupt")
        with self.assertRaises(TimelineError) as error:
            self.store.take_media(take_id)
        self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
