"""Per-shot media correctness; fake inference, real FFmpeg and filesystem."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import core


class Asset:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(path)

    def as_reference(self):
        return {"__type": "core/ASSET", "info": {"file_path": str(self.path)}}


class FakeClient:
    def __init__(self):
        self.assets = self
        self.closed = False

    def from_file(self, path):
        return Asset(path)

    def close(self):
        self.closed = True


class CopyEngine:
    """No model calls: record inputs and copy generated test media."""
    def __init__(self, root):
        self.root = root
        self.calls = []

    def edit_frame(self, client, image, prompt, **opts):
        self.prompt = prompt
        return image["info"]["file_path"]

    def propagate(self, client, video, edited, prompt, **opts):
        self.calls.append((video, opts))
        path = self.root / f"inference_{len(self.calls)}.mp4"
        shutil.copyfile(video["info"]["file_path"], path)
        return str(path)


class TestEditSegment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "media").mkdir()
        self.video = self.root / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=128x96:rate=24", "-frames:v", "25",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.video)], check=True)
        self.client = FakeClient()
        self.engine = CopyEngine(self.root)
        p = patch.object(core, "WORK", self.root)
        p.start()
        self.addCleanup(p.stop)

    def render(self, start, end):
        return core.edit_segment(self.video, {"start": start, "end": end}, "replace object",
                                 client=self.client, engine=self.engine,
                                 propagate={"frames": 121, "fps": 24})

    def test_full_video_frame_option_does_not_override_shot_length(self):
        result = self.render(0, 10)
        self.assertEqual(self.engine.calls[0][1]["frames"], 17)
        self.assertEqual(core.ffprobe(result)["frames"], 11)
        self.assertEqual(self.engine.prompt, "replace object")
        self.assertTrue(Path(result).is_absolute())

    def test_one_frame_shot_is_not_dropped(self):
        result = self.render(10, 10)
        self.assertEqual(self.engine.calls[0][1]["frames"], 9)
        self.assertEqual(core.ffprobe(result)["frames"], 1)

    def test_unique_workspaces_and_committed_video_references(self):
        self.render(0, 8)
        self.render(0, 8)
        a, b = [call[0] for call in self.engine.calls]
        self.assertIsInstance(a, dict)
        self.assertNotEqual(a["info"]["file_path"], b["info"]["file_path"])

    def test_odd_dimensions_preserve_frame_count(self):
        self.video = self.root / "odd.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc=size=129x97:rate=24", "-frames:v", "17",
                        "-c:v", "libx264", "-pix_fmt", "yuv444p", str(self.video)], check=True)
        result = self.render(0, 16)
        info = core.ffprobe(result)
        self.assertEqual(info["frames"], 17)
        self.assertEqual((info["width"], info["height"]), (130, 98))
        self.assertEqual(len(self.engine.calls), 1)

    def test_reverse_segment_raises(self):
        with self.assertRaises(ValueError):
            self.render(10, 5)
