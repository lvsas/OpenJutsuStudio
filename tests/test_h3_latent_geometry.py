"""A continuation keeps the parent's ratio, whatever the swap produced."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from h3_latent_geometry import continuity_geometry  # noqa: E402


class GeometryTests(unittest.TestCase):
    def assertConformant(self, width, height):
        self.assertEqual(width % 32, 0, 'width must be a multiple of 32')
        self.assertEqual(height % 32, 0, 'height must be a multiple of 32')

    def test_a_conformant_source_is_left_untouched(self):
        self.assertEqual(continuity_geometry(1280, 704), (1280, 704))

    def test_a_wide_source_keeps_its_ratio_within_tolerance(self):
        width, height = continuity_geometry(1920, 1080)
        self.assertConformant(width, height)
        self.assertAlmostEqual(width / height, 1920 / 1080, delta=0.02)
        self.assertLessEqual(width * height, 1_000_000)

    def test_a_portrait_source_stays_portrait(self):
        width, height = continuity_geometry(1080, 1920)
        self.assertConformant(width, height)
        self.assertGreater(height, width)
        self.assertAlmostEqual(width / height, 1080 / 1920, delta=0.02)

    def test_a_square_source_stays_square(self):
        width, height = continuity_geometry(1024, 1024)
        self.assertConformant(width, height)
        self.assertEqual(width, height)

    def test_an_odd_source_is_snapped_without_exceeding_the_budget(self):
        width, height = continuity_geometry(1991, 1087)
        self.assertConformant(width, height)
        self.assertLessEqual(width * height, 1_000_000)

    def test_a_tiny_source_is_not_inflated(self):
        width, height = continuity_geometry(320, 192)
        self.assertConformant(width, height)
        self.assertLessEqual(width, 320)

    def test_invalid_inputs_are_refused(self):
        for bad in ((0, 100), (100, 0), (-3, 5), (True, 100), (100.0, 100)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                continuity_geometry(*bad)
        with self.assertRaises(ValueError):
            continuity_geometry(100, 100, block=0)
        with self.assertRaises(ValueError):
            continuity_geometry(100, 100, max_megapixels=0)


if __name__ == '__main__':
    unittest.main()
