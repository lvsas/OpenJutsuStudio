"""A generation context never rewrites the take it belongs to."""
import sys
from pathlib import Path
import tempfile
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

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
        self.assertEqual([Path(item['filename']).suffix for item in manifest['references']],
                         ['.png', '.jpg'])
        paths = ctx.context_references(self.work, TAKE)
        self.assertEqual([p.read_bytes() for p in paths], [b'ONE', b'TWO'])

    def test_removing_one_renumbers_list_positions_without_renaming_files(self):
        ctx.add_reference(self.work, TAKE, b'ONE', '.png')
        before = ctx.add_reference(self.work, TAKE, b'TWO', '.png')
        manifest = ctx.remove_reference(self.work, TAKE, 1)
        self.assertEqual(manifest['references'], before['references'][1:])
        self.assertEqual(ctx.context_references(self.work, TAKE)[0].read_bytes(), b'TWO')

    def test_remove_then_add_with_mixed_suffixes_keeps_every_remaining_image(self):
        for payload, suffix in ((b'ONE', '.png'), (b'TWO', '.jpg'), (b'THREE', '.png')):
            ctx.add_reference(self.work, TAKE, payload, suffix)
        ctx.remove_reference(self.work, TAKE, 2)
        ctx.add_reference(self.work, TAKE, b'FOUR', '.png')
        paths = ctx.context_references(self.work, TAKE)
        self.assertEqual([p.read_bytes() for p in paths], [b'ONE', b'THREE', b'FOUR'])
        self.assertEqual(len(set(paths)), 3)

    def test_seed_copies_once_and_does_not_resolve_inheritance_after_empty_override(self):
        source = self.work / 'source.png'
        source.write_bytes(b'ORIGINAL')
        ctx.seed_context(self.work, TAKE, lambda: [source])
        copied = ctx.context_references(self.work, TAKE)[0]
        self.assertNotEqual(copied, source)
        self.assertEqual(copied.read_bytes(), b'ORIGINAL')
        ctx.remove_reference(self.work, TAKE, 1)
        with patch.object(source.__class__, 'read_bytes', side_effect=AssertionError('origin read')):
            ctx.seed_context(self.work, TAKE, lambda: self.fail('inherited was called'))
        self.assertTrue(ctx.has_context(self.work, TAKE))
        self.assertEqual(ctx.context_references(self.work, TAKE), [])
        self.assertEqual(source.read_bytes(), b'ORIGINAL')

    def test_incomplete_seed_never_publishes_a_partial_context(self):
        source = self.work / 'source.png'
        source.write_bytes(b'ORIGINAL')
        with self.assertRaises(ValueError):
            ctx.seed_context(self.work, TAKE, lambda: [source, self.work / 'missing.png'])
        self.assertFalse(ctx.has_context(self.work, TAKE))
        self.assertEqual(ctx.context_references(self.work, TAKE), [])

    def test_a_failed_replace_keeps_the_previous_file_and_manifest(self):
        before = ctx.add_reference(self.work, TAKE, b'ONE', '.png')
        with patch.object(ctx, '_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                ctx.replace_reference(self.work, TAKE, 1, b'TWO', '.jpg')
        self.assertEqual(ctx.context_manifest(self.work, TAKE), before)
        self.assertEqual(ctx.context_references(self.work, TAKE)[0].read_bytes(), b'ONE')

    def test_parallel_appends_do_not_lose_manifest_entries(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda n: ctx.add_reference(self.work, TAKE, str(n).encode(), '.png'),
                          range(20)))
        paths = ctx.context_references(self.work, TAKE)
        self.assertEqual(len(paths), 20)
        self.assertEqual({p.read_bytes() for p in paths}, {str(n).encode() for n in range(20)})

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
