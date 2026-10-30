"""The gallery picker chooses characters; the server still verifies them."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'src' / 'static' / 'gallery-picker.js').read_text()
PAGES = [(ROOT / 'src' / 'templates' / name).read_text() for name in ('index.html', 'h3.html')]


class GalleryPickerTests(unittest.TestCase):
    def test_both_swap_pages_load_the_picker(self):
        for page in PAGES:
            self.assertIn('/static/gallery-picker.js', page)

    def test_selection_is_sent_as_repeated_reference_ids(self):
        self.assertIn("name = 'reference_job_ids'", SCRIPT)
        self.assertIn("type = 'hidden'", SCRIPT)
        self.assertIn("hidden.value = id", SCRIPT)

    def test_an_empty_library_points_at_the_character_page(self):
        self.assertIn('/characters', SCRIPT)
        self.assertIn('No saved characters yet', SCRIPT)

    def test_the_picker_states_the_selection_and_its_limit(self):
        self.assertIn('selected', SCRIPT)
        self.assertIn('limit', SCRIPT)


if __name__ == '__main__':
    unittest.main()
