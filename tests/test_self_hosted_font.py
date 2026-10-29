"""The declared font stack must actually ship, with its licence."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'src/static/design-system.css').read_text()
FONT = ROOT / 'src/static/fonts/inter-variable-latin.woff2'
LICENCE = ROOT / 'src/static/fonts/LICENSE-Inter.txt'


class SelfHostedFontTests(unittest.TestCase):
    def test_inter_is_declared_for_the_stacks_that_name_it(self):
        self.assertIn('font-family: Inter', CSS)
        faces = re.findall(r'@font-face\s*{[^}]*}', CSS)
        self.assertTrue(any('inter-variable-latin.woff2' in face for face in faces),
                        'no @font-face delivers the Inter file')
        self.assertTrue(any('font-weight: 100 900' in face for face in faces if 'Inter' in face),
                        'the variable range must be declared, not a single weight')

    def test_font_file_and_licence_are_present_and_plausible(self):
        self.assertTrue(FONT.is_file(), 'the woff2 file is missing')
        self.assertGreater(FONT.stat().st_size, 10000)
        self.assertEqual(FONT.read_bytes()[:4], b'wOF2', 'not a woff2 file')
        self.assertTrue(LICENCE.is_file(), 'the OFL licence text is missing')
        text = LICENCE.read_text()
        self.assertIn('SIL Open Font License', text)
        self.assertIn('Inter Project Authors', text)

    def test_every_font_reference_resolves_to_a_shipped_file(self):
        for name in re.findall(r'url\("(/static/fonts/[^"]+)"\)', CSS):
            with self.subTest(font=name):
                self.assertTrue((ROOT / 'src' / name.lstrip('/')).is_file(), name)


if __name__ == '__main__':
    unittest.main()
