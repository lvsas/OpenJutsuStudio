"""CPU-only real FFmpeg regression tests: no inference or external media."""
import array
import errno
import json
import subprocess
import threading
import time
from unittest.mock import patch

from test_timeline_store import IsolatedTimeline, make_video
from timeline_models import EditProject
from timeline_store import TimelineError
from timeline_export import ExportManager
from media_probe import probe_mp4


class TimelineExportTests(IsolatedTimeline):
    def manager(self, **kwargs):
        manager = ExportManager(self.store, **kwargs)
        self.addCleanup(manager.close)
        return manager

    def await_export(self, manager, export_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = manager.get(export_id)
            if result["status"] in {"ready", "error"}:
                return result
            time.sleep(.02)
        self.fail("CPU export did not terminate")

    def test_actual_frames_order_trims_audio_and_snapshot(self):
        black = make_video(self.media / "black.mp4", color="black", frames=12, audio=True)
        white = make_video(self.media / "white.mp4", color="white", frames=12, size="48x64")
        project = self.store.create("Cut")
        project = self.store.import_job(project["project_id"], 0, self.job(black, "ltx25-ripple").id)
        project = self.store.import_job(project["project_id"], 1, self.job(white).id)
        first, second = project["clips"]
        project = self.store.edit(project["project_id"], EditProject(revision=2, clips=[
            {"clip_id": first["clip_id"], "in_frame": 2, "out_frame": 8},
            {"clip_id": second["clip_id"], "in_frame": 3, "out_frame": 7}]))
        manager = self.manager()
        result = manager.submit(project["project_id"], 3)
        duplicate = manager.submit(project["project_id"], 3)
        self.assertEqual(result["export_id"], duplicate["export_id"])
        # Snapshot owns this arrangement even after later removal.
        self.store.edit(project["project_id"], EditProject(revision=3, clips=[]))
        result = self.await_export(manager, result["export_id"])
        self.assertEqual(result["status"], "ready", result)
        path = manager.media(result["export_id"])
        self.assertEqual(probe_mp4(path)["frames"], 10)
        self.assertEqual((probe_mp4(path)["width"], probe_mp4(path)["height"]), (64, 48))
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True, timeout=30).stdout
        frame_bytes = 64 * 48 * 3
        for index in range(10):
            centre = raw[index * frame_bytes + (24 * 64 + 32) * 3]
            self.assertLess(centre, 10) if index < 6 else self.assertGreater(centre, 240)
        samples = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                                  "-ar", "48000", "-f", "f32le", "-"],
                                 capture_output=True, check=True, timeout=30).stdout
        audio = array.array("f", samples)
        def energy(start, end):
            values = audio[int(start * 48000):int(end * 48000)]
            return sum(x * x for x in values) / len(values)
        self.assertGreater(energy(.1, .4), .001)
        self.assertLess(energy(.6, .75), .00001)
        streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True, timeout=30).stdout)["streams"]
        self.assertEqual(streams[0]["codec_name"], "h264")
        self.assertEqual(streams[0]["pix_fmt"], "yuv420p")
        self.assertEqual(streams[1]["codec_name"], "aac")
        self.assertNotIn(str(self.work), str(result))
        manager.close()
        restarted = self.manager()
        self.assertEqual(restarted.get(result["export_id"]), result)
        self.assertEqual(restarted.media(result["export_id"]).read_bytes(), path.read_bytes())

    def test_reordered_fractional_rate_and_changed_asset(self):
        project, _ = self.imported(fps="30000/1001", frames=13)
        first = project["clips"][0]
        other = make_video(self.media / "other.mp4", color="white", fps="30000/1001", frames=9)
        project = self.store.import_job(project["project_id"], 1, self.job(other).id)
        second = project["clips"][1]
        project = self.store.edit(project["project_id"], EditProject(revision=2, clips=[
            {"clip_id": second["clip_id"], "in_frame": 1, "out_frame": 6},
            {"clip_id": first["clip_id"], "in_frame": 4, "out_frame": 11}]))
        manager = self.manager()
        result = self.await_export(manager, manager.submit(project["project_id"], 3)["export_id"])
        self.assertEqual(result["status"], "ready", result)
        path = manager.media(result["export_id"])
        media = probe_mp4(path)
        self.assertEqual(media["frames"], 12)
        self.assertAlmostEqual(media["fps"], 30000 / 1001, places=6)
        self.assertAlmostEqual(media["duration"], 12 * 1001 / 30000, places=5)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True, timeout=30).stdout
        frame_bytes = 64 * 48 * 3
        self.assertGreater(raw[(24 * 64 + 32) * 3], 240)
        self.assertLess(raw[5 * frame_bytes + (24 * 64 + 32) * 3], 10)
        self.store.take_media(first["take_id"]).write_bytes(b"mutated")
        with self.assertRaises(TimelineError) as error:
            manager.submit(project["project_id"], 3)
        self.assertEqual(error.exception.status_code, 409)

    def test_audio_alignment_uses_first_video_pts_not_container_zero(self):
        base = make_video(self.media / "base.mp4", audio=True)
        shifted = self.media / "shifted.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(base), "-itsoffset", "0.5", "-i", str(base),
                        "-map", "1:v:0", "-map", "0:a:0", "-c", "copy", str(shifted)],
                       capture_output=True, check=True, timeout=30)
        project = self.store.create("Offset audio")
        project = self.store.import_job(project["project_id"], 0, self.job(shifted).id)
        manager = self.manager()
        result = self.await_export(manager, manager.submit(project["project_id"], 1)["export_id"])
        self.assertEqual(result["status"], "ready", result)
        path = manager.media(result["export_id"])
        self.assertEqual(probe_mp4(path)["frames"], 12)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "48000",
                              "-f", "f32le", "-"], capture_output=True, check=True, timeout=30).stdout
        samples = array.array("f", raw)
        def energy(start, end):
            values = samples[int(start * 48000):int(end * 48000)]
            return sum(value * value for value in values) / len(values)
        self.assertGreater(energy(.1, .4), .001)
        self.assertLess(energy(.65, .9), .00001)

    def test_varying_frames_prove_nonzero_trim_offsets(self):
        path = self.media / "ramp.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "nullsrc=s=64x48:r=10,geq=lum='N*20':cb=128:cr=128",
                        "-frames:v", "10", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(path)],
                       capture_output=True, check=True, timeout=30)
        project = self.store.create("Ramp")
        project = self.store.import_job(project["project_id"], 0, self.job(path).id)
        clip_id = project["clips"][0]["clip_id"]
        project = self.store.edit(project["project_id"], EditProject(revision=1, clips=[
            {"clip_id": clip_id, "in_frame": 2, "out_frame": 7}]))
        manager = self.manager()
        result = self.await_export(manager, manager.submit(project["project_id"], 2)["export_id"])
        self.assertEqual(result["status"], "ready", result)
        def pixels(path):
            return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                  capture_output=True, check=True, timeout=30).stdout
        original = pixels(path)
        output = pixels(manager.media(result["export_id"]))
        stride = 64 * 48 * 3
        self.assertEqual(len(output), 5 * stride)
        for index in range(5):
            expected = original[(index + 2) * stride:(index + 3) * stride]
            actual = output[index * stride:(index + 1) * stride]
            self.assertLess(sum(abs(a - b) for a, b in zip(expected, actual)) / stride, 2)

    def test_odd_canvas_is_padded_up_without_losing_frames(self):
        path = self.media / "odd.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=129x97:r=24",
                        "-frames:v", "7", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv444p", str(path)],
                       capture_output=True, check=True, timeout=30)
        project = self.store.create("Odd canvas")
        project = self.store.import_job(project["project_id"], 0, self.job(path).id)
        manager = self.manager()
        result = self.await_export(manager, manager.submit(project["project_id"], 1)["export_id"])
        self.assertEqual(result["status"], "ready", result)
        media = probe_mp4(manager.media(result["export_id"]))
        self.assertEqual((media["frames"], media["width"], media["height"]), (7, 130, 98))

    def test_anamorphic_sources_preserve_display_geometry(self):
        for index, (sar, expected_aspect) in enumerate((("2/1", 4.0), ("1/2", 1.0))):
            with self.subTest(sar=sar):
                source = self.media / f"anamorphic{index}.mp4"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                                "color=c=red:s=96x48:r=24", "-frames:v", "8", "-vf", f"setsar={sar}",
                                "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(source)],
                               capture_output=True, check=True, timeout=30)
                project = self.store.create("Anamorphic fit")
                project = self.store.import_job(project["project_id"], 0, self.job(source).id)
                manager = self.manager()
                result = self.await_export(manager, manager.submit(project["project_id"], 1)["export_id"])
                self.assertEqual(result["status"], "ready", result)
                output = manager.media(result["export_id"])
                self.assertEqual(probe_mp4(output)["frames"], 8)
                raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-frames:v", "1",
                                      "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                     capture_output=True, check=True, timeout=30).stdout
                self.assertEqual(len(raw), 96 * 48 * 3)
                red = [(x, y) for y in range(48) for x in range(96)
                       if raw[(y*96+x)*3] > 160
                       and raw[(y*96+x)*3+1] < 60 and raw[(y*96+x)*3+2] < 60]
                self.assertTrue(red)
                content_width = max(x for x, _ in red) - min(x for x, _ in red) + 1
                content_height = max(y for _, y in red) - min(y for _, y in red) + 1
                self.assertAlmostEqual(content_width / content_height, expected_aspect, delta=.05)

    def test_mixed_fps_conflict_and_empty_project(self):
        project, _ = self.imported()
        path = make_video(self.media / "other.mp4", fps="24")
        project = self.store.import_job(project["project_id"], 1, self.job(path).id)
        manager = self.manager()
        with self.assertRaises(TimelineError) as error:
            manager.submit(project["project_id"], 2)
        self.assertEqual(error.exception.status_code, 409)
        empty = self.store.create("Empty")
        with self.assertRaises(TimelineError):
            manager.submit(empty["project_id"], 0)

    def test_interrupted_persisted_attempt_becomes_error_and_can_retry(self):
        import uuid
        from timeline_store import atomic_json
        project, _ = self.imported()
        export_id = uuid.uuid4().hex
        directory = self.work / "timeline" / "exports" / export_id
        directory.mkdir()
        atomic_json(directory / "snapshot.json", self.store.snapshot(project["project_id"], 1))
        atomic_json(directory / "status.json", {"export_id": export_id, "project_id": project["project_id"],
                    "revision": 1, "status": "queued", "error": None})
        manager = self.manager()
        interrupted = manager.get(export_id)
        self.assertEqual(interrupted["status"], "error")
        self.assertIn("restart", interrupted["error"])
        result = manager.submit(project["project_id"], 1)
        self.assertNotEqual(result["export_id"], export_id)
        result = self.await_export(manager, result["export_id"])
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(manager.get(export_id), interrupted)

    def test_enospc_terminal_status_recovers_without_closing_manager(self):
        from timeline_store import atomic_json
        for first_access in ("get", "submit"):
            with self.subTest(first_access=first_access):
                project, _ = self.imported()
                manager = self.manager(workers=1, max_queued=0)
                failed_writes = []

                def disk_full(path, state):
                    if state.get("status") == "error":
                        failed_writes.append(path)
                        # Fail the real atomic writer at flush, not the status read.
                        with patch("timeline_store.os.fsync", side_effect=OSError(
                                errno.ENOSPC, "private /secret/status.json")):
                            return atomic_json(path, state)
                    return atomic_json(path, state)

                def failed_render(store, snapshot, output, timeout):
                    output.write_bytes(b"unpublished partial render")
                    raise OSError(errno.ENOSPC, "private /secret/render.mp4")

                with patch("timeline_export.atomic_json", side_effect=disk_full), patch(
                        "timeline_export.render_snapshot", side_effect=failed_render):
                    failed = manager.submit(project["project_id"], 1)
                    # Drain the sole worker, keeping the manager and pool open.
                    manager._queue._pool.submit(lambda: None).result(timeout=10)
                    directory = self.store.root / "exports" / failed["export_id"]
                    self.assertTrue(failed_writes)
                    self.assertEqual(json.loads((directory / "status.json").read_text())["status"], "running")
                    self.assertTrue(manager._queue._slots.acquire(blocking=False))
                    self.assertFalse(manager._queue._slots.acquire(blocking=False))
                    manager._queue._slots.release()
                    if first_access == "get":
                        self.assertEqual(manager.get(failed["export_id"])["status"], "error")
                        with self.assertRaises(TimelineError) as error:
                            manager.media(failed["export_id"])
                        self.assertEqual(error.exception.status_code, 409)
                        for _ in range(3):
                            with self.assertRaises(TimelineError) as error:
                                manager.submit(project["project_id"], 1)
                            self.assertEqual(error.exception.status_code, 503)
                        self.assertEqual(len(manager._queue._terminal_failures), 1)
                        self.assertEqual(list((self.store.root / "exports").iterdir()), [directory])

                # Recovery must work even when submit (dedup) is the first reader.
                retried = manager.submit(project["project_id"], 1) if first_access == "submit" else None
                recovered = manager.get(failed["export_id"])
                self.assertEqual(recovered["status"], "error", recovered)
                self.assertEqual(json.loads((directory / "status.json").read_text())["status"], "error")
                self.assertIsNone(recovered["preview_url"])
                self.assertIsNone(recovered["download_url"])
                self.assertNotIn("/secret", str(recovered))
                self.assertNotIn(str(self.work), str(recovered))
                self.assertFalse((directory / "video.mp4").exists())
                with self.assertRaises(TimelineError) as error:
                    manager.media(failed["export_id"])
                self.assertEqual(error.exception.status_code, 409)
                if retried is None:
                    retried = manager.submit(project["project_id"], 1)
                self.assertNotEqual(retried["export_id"], failed["export_id"])
                result = self.await_export(manager, retried["export_id"])
                self.assertEqual(result["status"], "ready", result)
                self.assertEqual(probe_mp4(manager.media(result["export_id"]))["frames"], 12)
                manager._queue._pool.submit(lambda: None).result(timeout=10)
                self.assertTrue(manager._queue._slots.acquire(blocking=False))
                self.assertFalse(manager._queue._slots.acquire(blocking=False))
                manager._queue._slots.release()
                self.assertEqual(list((self.store.root / "staging").iterdir()), [])
                manager.close()

    def test_bounded_queue_and_sanitized_failure(self):
        entered, release = threading.Event(), threading.Event()
        def failing(*args):
            entered.set()
            release.wait(10)
            raise RuntimeError("private /secret/path")
        with patch("timeline_export.render_snapshot", side_effect=failing):
            manager = self.manager(workers=1, max_queued=0)
            project, _ = self.imported()
            result = manager.submit(project["project_id"], 1)
            self.assertTrue(entered.wait(5))
            second_manager = self.manager()
            self.assertEqual(second_manager.submit(project["project_id"], 1)["export_id"], result["export_id"])
            second_manager.close()
            self.assertEqual(manager.get(result["export_id"])["status"], "running")
            self.assertEqual(manager.submit(project["project_id"], 1)["export_id"], result["export_id"])
            other, _ = self.imported()
            with self.assertRaises(TimelineError) as error:
                manager.submit(other["project_id"], 1)
            self.assertEqual(error.exception.status_code, 503)
            release.set()
            result = self.await_export(manager, result["export_id"])
            self.assertEqual(result["status"], "error")
            self.assertNotIn("/secret", result["error"])
            self.assertIsNone(result["preview_url"])
            retried = manager.submit(project["project_id"], 1)
            self.assertNotEqual(retried["export_id"], result["export_id"])
            retried = self.await_export(manager, retried["export_id"])
            self.assertEqual(retried["status"], "error")
            self.assertEqual(manager.get(result["export_id"]), result)
            self.assertEqual(list((self.work / "timeline" / "staging").iterdir()), [])
