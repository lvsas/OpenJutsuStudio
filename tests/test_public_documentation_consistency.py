"""Public contribution guidance must agree with the shipped repository."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PublicDocumentationConsistencyTests(unittest.TestCase):
    def test_contribution_license_matches_the_product_license(self):
        license_text = (ROOT / 'LICENSE').read_text()
        contribution = (ROOT / 'CONTRIBUTING.md').read_text()
        self.assertIn('Apache License', license_text)
        self.assertIn('[Apache-2.0](LICENSE)', contribution)
        self.assertNotIn('[MIT license](LICENSE)', contribution)

    def test_contribution_points_to_the_shipped_ci(self):
        workflow = ROOT / '.github/workflows/tests.yml'
        self.assertTrue(workflow.is_file())
        contribution = (ROOT / 'CONTRIBUTING.md').read_text()
        self.assertIn('.github/workflows/tests.yml', contribution)
        self.assertNotIn('There is no checked-in CI workflow', contribution)

    def test_roadmap_does_not_promise_the_retired_container(self):
        roadmap = (ROOT / 'ROADMAP.md').read_text()
        self.assertNotIn('and a container for people who prefer that', roadmap)


if __name__ == '__main__':
    unittest.main()
