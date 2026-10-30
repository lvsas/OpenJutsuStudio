"""The gallery fills an existing reference slot; it is not a second widget beside it."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'src' / 'static' / 'gallery-picker.js').read_text()
PAGES = [(ROOT / 'src' / 'templates' / name).read_text() for name in ('index.html', 'h3.html')]


class GallerySlotTests(unittest.TestCase):
    def test_both_swap_pages_load_the_picker(self):
        for page in PAGES:
            self.assertIn('/static/gallery-picker.js', page)

    def test_each_file_slot_gets_its_own_button(self):
        self.assertIn('gallery-slot-open', SCRIPT)
        self.assertIn('gallerySlot', SCRIPT)

    def test_the_form_describes_every_slot_in_order(self):
        self.assertIn("hidden.name = 'reference_sources'", SCRIPT)
        self.assertIn("'gallery:' + picked", SCRIPT)
        self.assertIn("'upload'", SCRIPT)

    def test_choosing_a_character_clears_that_slots_file(self):
        self.assertIn("input.value = ''", SCRIPT)

    def test_an_empty_library_points_at_the_character_page(self):
        self.assertIn('/characters', SCRIPT)
        self.assertIn('No saved characters yet', SCRIPT)


if __name__ == '__main__':
    unittest.main()
