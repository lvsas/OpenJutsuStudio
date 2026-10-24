"""Static CSS contracts; viewport geometry is verified separately in the browser."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'src/static/continuity-studio.css').read_text()
BASE = CSS.split('@media', 1)[0]
MOBILE = CSS.split('@media(max-width:800px){', 1)[1].split('\n}', 1)[0]


def declarations(source, selector):
    match = re.search(re.escape(selector) + r'\s*\{([^{}]*)\}', source)
    if match is None:
        raise AssertionError(f'Missing CSS rule: {selector}')
    return dict(item.strip().split(':', 1) for item in match[1].split(';') if item.strip())


class SequenceSpacingUITests(unittest.TestCase):
    def test_main_owns_the_gap_without_extra_rail_margins(self):
        main = declarations(BASE, '.sequence-main')
        self.assertEqual(main['gap'], '1rem')
        self.assertEqual(main['min-width'], '0')
        rail_rules = re.findall(r'\.sequence-rail\s*\{([^{}]*)\}', CSS)
        self.assertTrue(rail_rules)
        for body in rail_rules:
            for name, value in (item.strip().split(':', 1) for item in body.split(';') if item.strip()):
                if name.startswith('margin'):
                    self.assertEqual(value, '0', 'Rail margins must not duplicate the parent gap')
        self.assertNotIn('gap', declarations(MOBILE, '.sequence-main'))

    def test_mobile_sequence_has_only_export_and_add(self):
        actions = declarations(MOBILE, '.sequence-rail-actions')
        self.assertEqual(actions['display'], 'grid')
        self.assertEqual(actions['grid-template-columns'], 'repeat(2,minmax(0,1fr))')
        for rule in (actions, declarations(MOBILE, '.sequence-rail-actions .btn')):
            self.assertNotIn('grid-row', rule)
            self.assertNotIn('grid-column', rule)
        self.assertNotRegex(CSS, r'#native-(?:library-toggle|export|refresh)\s*\{')

    def test_removed_project_controls_leave_no_css(self):
        for obsolete in ('.sequence-name', '#native-new-sequence', '#native-project-picker',
                         '.sequence-toolbar'):
            self.assertNotIn(obsolete, CSS)
        status = declarations(BASE, '#native-save-state')
        self.assertEqual(status['overflow-wrap'], 'anywhere')

    def test_library_has_bounded_responsive_width(self):
        library = declarations(BASE, '.sequence-library')
        self.assertEqual(library['flex'], '0 0 clamp(296px,26vw,320px)')
        self.assertEqual(library['min-width'], '0')
        mobile = declarations(MOBILE, '.sequence-library')
        self.assertEqual(mobile['flex'], 'none')
        self.assertEqual(mobile['width'], '100%')

    def test_library_scope_label_and_control_cannot_compete_for_width(self):
        label = declarations(BASE, '.sequence-library>label:not(.sr-only)')
        self.assertEqual(label['display'], 'grid')
        self.assertEqual(label['gap'], '.35rem')
        controls = declarations(BASE, '.sequence-library input,.sequence-library select')
        self.assertEqual(controls['width'], '100%')
        self.assertEqual(controls['max-width'], '100%')
        self.assertEqual(controls['min-width'], '0')
        self.assertEqual(declarations(BASE, '.library-take')['gap'], '.5rem')
        self.assertEqual(declarations(BASE, '.library-take')['padding'], '.5rem')

    def test_toolbar_and_library_touch_targets_stay_44px(self):
        for source, selector in ((BASE, '.sequence-rail-actions .btn,.library-tools .btn'),
                                 (MOBILE, '.sequence-rail-actions .btn')):
            rule = declarations(source, selector)
            self.assertEqual(rule['min-height'], '44px')
            self.assertEqual(rule['min-width'], '44px')
        for selector in ('.sequence-library input,.sequence-library select', '.library-preview',
                         '.library-add', '.sequence-library>.btn'):
            self.assertEqual(declarations(BASE, selector)['min-height'], '44px')

    def test_mobile_story_order_stays_rail_composer_preview(self):
        self.assertEqual(declarations(CSS, '.sequence-rail')['order'], '-1')
        workspace = declarations(MOBILE, '.native-workspace')
        self.assertEqual(workspace['display'], 'flex')
        self.assertEqual(workspace['flex-direction'], 'column')
        self.assertEqual(declarations(MOBILE, '.sequence-composer')['order'], '-1')


if __name__ == '__main__':
    unittest.main()
