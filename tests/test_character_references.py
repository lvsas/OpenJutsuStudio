"""Saved characters become swap references without a second trust path."""
import unittest

from character_library import LibraryError
from character_references import resolve


class FakeLibrary:
    def __init__(self, images, failures=None):
        self.images, self.failures, self.asked = images, failures or {}, []

    def completed_image(self, job_id):
        self.asked.append(job_id)
        if job_id in self.failures:
            raise LibraryError(409, self.failures[job_id])
        return self.images[job_id]


class ResolveTests(unittest.TestCase):
    def test_returns_the_verified_paths_in_selection_order(self):
        library = FakeLibrary({'a' * 32: '/m/a.png', 'b' * 32: '/m/b.png'})
        paths, reasons = resolve(['b' * 32, 'a' * 32], library, 2)
        self.assertEqual(paths, ['/m/b.png', '/m/a.png'])
        self.assertEqual(reasons, [])

    def test_one_broken_character_does_not_hide_the_others(self):
        library = FakeLibrary({'a' * 32: '/m/a.png'},
                              {'b' * 32: 'The generated image changed on disk since the job finished.'})
        paths, reasons = resolve(['a' * 32, 'b' * 32], library, 2)
        self.assertEqual(paths, ['/m/a.png'])
        self.assertEqual(len(reasons), 1)
        self.assertIn('changed on disk', reasons[0])
        self.assertIn('b' * 8, reasons[0])

    def test_duplicates_are_selected_once(self):
        library = FakeLibrary({'a' * 32: '/m/a.png'})
        paths, _ = resolve(['a' * 32, 'a' * 32], library, 3)
        self.assertEqual(paths, ['/m/a.png'])
        self.assertEqual(library.asked, ['a' * 32])

    def test_nothing_is_asked_beyond_the_limit(self):
        library = FakeLibrary({'a' * 32: '/m/a.png', 'b' * 32: '/m/b.png'})
        paths, reasons = resolve(['a' * 32, 'b' * 32], library, 1)
        self.assertEqual(paths, ['/m/a.png'])
        self.assertEqual(len(reasons), 1)
        self.assertIn('Only 1', reasons[0])


if __name__ == '__main__':
    unittest.main()
