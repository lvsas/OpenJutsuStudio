"""Pipeline orchestration only: mocked media/inference, real temporary Job files.

These are not GPU integration tests. No source clip, FFmpeg or server is used.
"""
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import ANY, MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import core
from tests.media_fixtures import TOTAL_FRAMES, TWO_SHOTS


class TestPipelineWithCuts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.video = self.root / "deliberately_absent_source.mp4"
        self.segments = [str(self.root / name) for name in ("seg1.mp4", "seg2.mp4")]
        self.merged = str(self.root / "merged.mp4")
        self.upscaled = str(self.root / "upscaled.mp4")
        self.client = MagicMock()
        self.engine = MagicMock()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(core, "WORK", self.root))
        stack.enter_context(patch("media.WORK", self.root))
        stack.enter_context(patch.object(core, "ENGINES", {"ltx25-ripple": self.engine}))
        self.make_client = stack.enter_context(
            patch.object(core, "make_client", return_value=self.client))
        self.detect = stack.enter_context(
            patch.object(core, "detect_scenes", return_value=TWO_SHOTS))
        self.edit = stack.enter_context(
            patch.object(core, "edit_segment", side_effect=self.segments))
        self.merge = stack.enter_context(
            patch.object(core, "merge_segments", return_value=self.merged))
        self.upscale = stack.enter_context(
            patch.object(core, "upscale_video", return_value=self.upscaled))
        # Fail loudly if any supposedly mocked stage starts a media subprocess.
        stack.enter_context(patch("subprocess.run", side_effect=AssertionError("unexpected media call")))

    def assert_persisted(self, job):
        self.assertEqual(job.path, self.root / "jobs" / f"{job.id}.json")
        saved = core.Job.load(job.id)
        self.assertEqual(saved.status, job.status)
        self.assertEqual(saved.result, job.result)
        self.assertEqual(saved.error, job.error)
        self.assertEqual(saved.progress, job.progress)
        self.assertEqual(saved.finished, job.finished)
        self.assertIsNotNone(saved.started)
        self.assertIsNotNone(saved.finished)

    def test_pipeline_detects_cuts_and_edits_per_segment(self):
        job = core.Job(id="two-shots", prompt="Replace riders with knights")
        core.run_pipeline(job, self.video, {"prompt": job.prompt})

        self.assertFalse(self.video.exists(), "No source clip is needed for orchestration")
        self.detect.assert_called_once_with(self.video)
        self.make_client.assert_called_once_with()
        self.assertEqual(self.edit.call_args_list, [
            call(video_path=self.video, segment=segment, prompt=job.prompt,
                 client=self.client, engine=self.engine, on_progress=ANY)
            for segment in TWO_SHOTS
        ])
        self.merge.assert_called_once_with(self.segments)
        self.upscale.assert_not_called()
        self.assertEqual(job.status, "done")
        self.assertEqual(job.result, self.merged)
        self.assertEqual(job.progress, 1.0)
        self.client.close.assert_called_once_with()
        self.assert_persisted(job)

    def test_pipeline_single_segment_no_merge(self):
        job = core.Job(id="one-shot", prompt="Replace with dragon")
        self.detect.return_value = [{"start": 0, "end": TOTAL_FRAMES - 1}]
        self.edit.side_effect = None
        self.edit.return_value = self.segments[0]
        core.run_pipeline(job, self.video, {"prompt": job.prompt})

        self.edit.assert_called_once()
        self.merge.assert_not_called()
        self.upscale.assert_not_called()
        self.assertEqual(job.status, "done")
        self.assertEqual(job.result, self.segments[0])
        self.client.close.assert_called_once_with()
        self.assert_persisted(job)

    def test_pipeline_upscales_after_merge(self):
        job = core.Job(id="upscale", prompt="Replace riders with knights")
        order = MagicMock()
        order.attach_mock(self.merge, "merge")
        order.attach_mock(self.upscale, "upscale")
        core.run_pipeline(job, self.video, {"upscale": True, "upscale_scale": 3.0})

        self.assertEqual(order.mock_calls, [
            call.merge(self.segments), call.upscale(self.merged, scale=3.0),
        ])
        self.assertEqual(job.status, "done")
        self.assertEqual(job.result, self.upscaled)
        self.client.close.assert_called_once_with()
        self.assert_persisted(job)

    def test_pipeline_handles_empty_video(self):
        job = core.Job(id="empty")
        self.detect.return_value = []
        core.run_pipeline(job, self.video, {})

        self.assertEqual(job.status, "error")
        self.assertIn("no scenes", job.error.lower())
        self.make_client.assert_not_called()
        self.edit.assert_not_called()
        self.merge.assert_not_called()
        self.upscale.assert_not_called()
        self.client.close.assert_not_called()
        self.assert_persisted(job)

    def test_stage_failures_persist_error_and_close_owned_client(self):
        stages = [
            ("detection", self.detect, False),
            ("client", self.make_client, False),
            ("editing", self.edit, True),
            ("merging", self.merge, True),
            ("upscaling", self.upscale, True),
        ]
        for name, stage, client_created in stages:
            with self.subTest(stage=name):
                self.client.reset_mock()
                for _, mock, _ in stages:
                    mock.reset_mock(side_effect=True)
                self.edit.side_effect = list(self.segments)
                stage.side_effect = RuntimeError(f"{name} failed")
                job = core.Job(id=f"failed-{name}", prompt="edit")
                core.run_pipeline(job, self.video, {"upscale": True})
                self.assertEqual(job.status, "error")
                self.assertIn(f"{name} failed", job.error)
                self.assertIsNone(job.result)
                if client_created:
                    self.client.close.assert_called_once_with()
                else:
                    self.client.close.assert_not_called()
                self.assert_persisted(job)


if __name__ == "__main__":
    unittest.main()
