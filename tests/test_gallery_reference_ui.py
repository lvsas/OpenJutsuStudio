"""The gallery is a chooser for the existing reference field, not a second path.

`applyCharacterReference` already turns a character id into a real File inside the
input and dispatches `change`, which is what paints the picker. Reusing it is the
only reason a gallery choice looks like a normal one.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'src' / 'static' / 'gallery-picker.js').read_text()
PAGES = [(ROOT / 'src' / 'templates' / name).read_text() for name in ('index.html', 'h3.html')]


class GalleryChooserTests(unittest.TestCase):
    def test_both_swap_pages_load_the_chooser_as_a_module(self):
        for page in PAGES:
            self.assertIn('/static/gallery-picker.js" type="module"', page)

    def test_the_chooser_reuses_the_working_handoff(self):
        self.assertIn("from '/static/character-handoff.js'", SCRIPT)
        self.assertIn('applyCharacterReference', SCRIPT)
        self.assertIn("params.set('character_id'", SCRIPT)

    def test_the_chooser_owns_no_second_server_contract(self):
        self.assertNotIn('reference_sources', SCRIPT)
        self.assertNotIn('reference_job_ids', SCRIPT)

    def test_a_filled_or_disabled_slot_offers_no_deception(self):
        self.assertIn('button.disabled', SCRIPT)
        self.assertIn('Remove the current character reference', SCRIPT)
        self.assertIn('Enable this reference slot first', SCRIPT)

    def test_a_slot_enabled_later_still_gets_a_button(self):
        self.assertIn('MutationObserver', SCRIPT)
        self.assertIn("attributeFilter: ['disabled']", SCRIPT)
        self.assertIn('button.disabled !== next', SCRIPT)

    def test_an_empty_library_points_at_the_character_page(self):
        self.assertIn('/characters', SCRIPT)
        self.assertIn('No saved characters yet', SCRIPT)
