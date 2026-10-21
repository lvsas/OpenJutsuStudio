"""A generation context never rewrites the take it belongs to."""
import sys
from pathlib import Path
import tempfile
import os
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import continuity_context as ctx  # noqa: E402

TAKE = 'a' * 32


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)

    def test_an_empty_context_means_no_prepared_references(self):
        self.assertEqual(ctx.context_references(self.work, TAKE), [])

    def test_added_references_keep_their_order(self):
        ctx.add_reference(self.work, TAKE, b'ONE', '.png')
        manifest = ctx.add_reference(self.work, TAKE, b'TWO', '.jpg')
        self.assertEqual([item['filename'] for item in manifest['references']],
                         ['reference-1.png', 'reference-2.jpg'])
        paths = ctx.context_references(self.work, TAKE)
        self.assertEqual([p.read_bytes() for p in paths], [b'ONE', b'TWO'])

    def test_removing_one_renumbers_the_rest_so_picture_numbers_stay_contiguous(self):
        ctx.add_reference(self.work, TAKE, b'ONE', '.png')
        ctx.add_reference(self.work, TAKE, b'TWO', '.png')
        manifest = ctx.remove_reference(self.work, TAKE, 1)
        self.assertEqual([item['filename'] for item in manifest['references']],
                         ['reference-1.png'])
        self.assertEqual(ctx.context_references(self.work, TAKE)[0].read_bytes(), b'TWO')

    def test_a_non_image_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'PNG, JPEG or WebP'):
            ctx.add_reference(self.work, TAKE, b'x', '.txt')

    def test_an_empty_payload_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'empty'):
            ctx.add_reference(self.work, TAKE, b'', '.png')

    def test_a_bad_take_identifier_is_refused(self):
        with self.assertRaises(ValueError):
            ctx.context_references(self.work, '../escape')


if __name__ == '__main__':
    unittest.main()
