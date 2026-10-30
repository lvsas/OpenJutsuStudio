"""Every character the studio can generate must be one it can save.

build_capsule puts a recipe into envelope 2 unless the recipe is 6 or 7. Bumping
the recipe schema without widening that envelope makes every new character
unsavable, with a message about a contract rather than about a constant.
"""
import unittest

from character_capsule import allowed_recipe_versions
from character_recipe import SCHEMA_VERSION


class EnvelopeCoverageTests(unittest.TestCase):
    def test_the_current_recipe_is_accepted_by_the_envelope_it_lands_in(self):
        envelope = SCHEMA_VERSION if SCHEMA_VERSION in (6, 7) else 2
        self.assertIn(SCHEMA_VERSION, allowed_recipe_versions(envelope),
                      'a bumped recipe schema must widen ENVELOPE_RECIPES')

    def test_the_oldest_envelope_still_refuses_newer_contracts(self):
        self.assertNotIn(SCHEMA_VERSION, allowed_recipe_versions(1))


if __name__ == '__main__':
    unittest.main()
