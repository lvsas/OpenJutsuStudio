"""Scene detection must not depend on the development clip's cut/fps/aspect."""
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scenes import detect_scenes


class DiverseSceneTests(unittest.TestCase):
    def test_varied_cuts_rates_and_aspects(self):
        rng = random.Random(927)
        with tempfile.TemporaryDirectory() as tmp:
            for index, rate in enumerate([12, 24, 25, "30000/1001"]):
                count = rng.randint(20, 80)
                cut = rng.randint(1, count - 1)
                size = ["64x96", "96x64", "80x80", "64x96"][index]
                with self.subTest(rate=rate, count=count, cut=cut, size=size):
                    path = Path(tmp) / f"case-{index}.mp4"
                    subprocess.run([
                        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        f"color=c=black:s={size}:r={rate}", "-vf",
                        f"drawbox=c=white:t=fill:enable='gte(n,{cut})'", "-frames:v", str(count),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
                    ], capture_output=True, check=True, timeout=30)
                    self.assertEqual(detect_scenes(path), [
                        {"start": 0, "end": cut - 1}, {"start": cut, "end": count - 1}])
