"""The take rail must stay one line tall, even with a single take.

Measured before the fix: with one take, `.library-take` was 286x151 px and
`.library-preview` was squeezed to 98x133, so the title stacked vertically.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'src/static/continuity-studio.css').read_text()


def rule(selector: str) -> str:
    match = re.search(re.escape(selector) + r'\{([^}]*)\}', CSS)
    assert match, f'{selector} missing from continuity-studio.css'
    return match.group(1)


class LibraryRailLayout(unittest.TestCase):
    def test_the_row_wraps(self):
        self.assertIn('flex-wrap:wrap', rule('.library-take'))

    def test_the_preview_owns_the_whole_first_line(self):
        self.assertIn('flex:1 1 100%', rule('.library-preview'))

    def test_the_actions_align_to_the_end_of_their_line(self):
        self.assertIn('justify-content:flex-end', rule('.library-take'))

    def test_the_buttons_stay_compact(self):
        self.assertIn('font-size:.62rem', rule('.library-take .btn'))


if __name__ == '__main__':
    unittest.main()
