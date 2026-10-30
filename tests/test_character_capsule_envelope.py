"""One description of a capsule's artifacts, used by writing and by validation."""
import unittest

from character_capsule import allowed_recipe_versions, expected_assets
from character_recipe import SCHEMA_VERSION


class EnvelopeCoverageTests(unittest.TestCase):
    def test_the_current_recipe_is_accepted_by_the_envelope_it_lands_in(self):
        envelope = SCHEMA_VERSION if SCHEMA_VERSION in (6, 7) else 2
        self.assertIn(SCHEMA_VERSION, allowed_recipe_versions(envelope),
                      'a bumped recipe schema must widen ENVELOPE_RECIPES')

    def test_the_oldest_envelope_still_refuses_newer_contracts(self):
        self.assertNotIn(SCHEMA_VERSION, allowed_recipe_versions(1))

    def test_a_plain_character_holds_two_artifacts(self):
        self.assertEqual(expected_assets({'face_refine': False}), {'image', 'caption'})

    def test_a_refined_face_holds_its_base_image(self):
        self.assertEqual(expected_assets({'face_refine': True}), {'image', 'caption', 'base_image'})
