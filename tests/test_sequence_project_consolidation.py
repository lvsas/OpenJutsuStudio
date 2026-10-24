"""Surface ownership contracts; interaction/layout are verified separately."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SequenceProjectConsolidation(unittest.TestCase):
    def test_project_controls_have_one_owner_without_phantom_listeners(self):
        page = (ROOT / 'src/templates/timeline.html').read_text()
        controller = (ROOT / 'src/static/sequence-workspace.js').read_text()
        shared = (ROOT / 'src/static/project-session.js').read_text()
        for retired in ('native-project-title', 'native-project-picker', 'native-new-sequence'):
            self.assertNotIn(retired, page)
            self.assertNotIn(retired, controller)
            self.assertNotIn(retired, shared)
        for retired in ('sequence-toolbar', 'native-legacy-open', 'native-project-kind', 'native-library-toggle'):
            self.assertNotIn(retired, page)
            self.assertNotIn(retired, controller)
        self.assertNotIn('/assembly', controller)
        self.assertIn('class="studio-intro sequence-intro"', page)
        self.assertIn('id="sequence-title"', page)
        self.assertLess(page.index('class="studio-wip"'), page.index('<main'))
        self.assertEqual(page.count('class="studio-wip"'), 1)
        css = (ROOT / 'src/static/continuity-studio.css').read_text()
        self.assertNotIn('.studio-wip', css, 'Use the shared banner styles without page overrides')
        self.assertIn('<h2 class="eyebrow">Your sequence</h2>', page)
        self.assertIn('id="native-save-state"', page)
        self.assertIn('id="native-reload"', page)
        self.assertIn('beforeNavigate', controller)
        self.assertIn('onRenamed', controller)

    def test_scope_and_explicit_actions_are_retained(self):
        page = (ROOT / 'src/templates/timeline.html').read_text()
        self.assertRegex(page, r'id="native-library-scope"[^>]*>\s*<option value="project">')
        self.assertIn('value="common"', page)
        for control in ('native-export', 'native-refresh', 'native-rail-add'):
            self.assertEqual(len(re.findall(r'\bid="' + control + '"', page)), 1)
        self.assertIn('id="forward-submit"', page)
