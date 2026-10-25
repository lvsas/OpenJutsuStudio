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

    def test_empty_positions_are_modestly_smaller_without_clipping_labels(self):
        empty = declarations(CSS, '.sequence-gap')
        full = declarations(CSS, '.sequence-slot')
        width = float(empty['flex'].split()[-1].removesuffix('px'))
        full_width = float(full['flex'].split()[-1].removesuffix('px'))
        self.assertGreaterEqual(width / full_width, .8)
        self.assertLessEqual(width / full_width, .86)
        button = declarations(CSS, '.position-create')
        self.assertEqual(button['min-height'], '112px')
        for selector in ('.position-create', '.position-create strong', '.position-create small'):
            rule = declarations(CSS, selector)
            self.assertNotIn(rule.get('overflow'), ('hidden', 'clip'))
            self.assertNotEqual(rule.get('white-space'), 'nowrap')
        self.assertEqual(declarations(CSS, '.position-mark')['line-height'], '1')

    def test_mobile_empty_positions_keep_readable_copy_and_touch_area(self):
        button = declarations(MOBILE, '.position-create')
        self.assertEqual(button['display'], 'grid')
        self.assertEqual(button['min-height'], '96px')
        self.assertEqual(declarations(MOBILE, '.position-mark')['grid-row'], '1/3')
        self.assertEqual(declarations(CSS, '.position-create:focus-visible')['outline-offset'], '3px')
        self.assertEqual(declarations(CSS, '.board-track')['padding'], '.65rem 5px .25rem')

    def test_library_height_follows_main_not_the_number_of_takes(self):
        self.assertEqual(declarations(BASE, '.sequence-workbench')['align-items'], 'stretch')
        library = declarations(BASE, '.sequence-library')
        self.assertEqual(library['contain'], 'size')
        self.assertEqual(library['display'], 'flex')
        self.assertEqual(library['flex-direction'], 'column')
        self.assertEqual(library['min-height'], '0')
        self.assertEqual(declarations(MOBILE, '.sequence-library')['contain'], 'none')

    def test_library_list_fills_available_height_with_viewport_scroll_bound(self):
        takes = declarations(BASE, '.library-takes')
        self.assertEqual(takes['flex'], '1 1 auto')
        self.assertEqual(takes['min-height'], '0')
        self.assertEqual(takes['max-height'], '100dvh')
        self.assertEqual(takes['overflow-y'], 'auto')
        self.assertEqual(takes['align-content'], 'start')
        mobile = declarations(MOBILE, '.library-takes')
        self.assertEqual(mobile['max-height'], 'min(30vh,250px)')
        self.assertEqual(mobile['flex'], 'none')

    def test_mobile_story_order_stays_rail_composer_preview(self):
        self.assertEqual(declarations(CSS, '.sequence-rail')['order'], '-1')
        workspace = declarations(MOBILE, '.native-workspace')
        self.assertEqual(workspace['display'], 'flex')
        self.assertEqual(workspace['flex-direction'], 'column')
        self.assertEqual(declarations(MOBILE, '.sequence-composer')['order'], '-1')


if __name__ == '__main__':
    unittest.main()
