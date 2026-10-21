"""The H3 prompt job keeps the authored policy and only fills the user slot."""
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import h3_prompt_generator as gen  # noqa: E402

REF = {'__type': 'core/ASSET', 'info': {'id': 'committed-ref'}}


class PromptGraphTests(unittest.TestCase):
    def test_the_authored_guide_is_copied_byte_for_byte(self):
        original = json.loads(gen.TEMPLATE.read_text())['5833_26']['inputs']['string']
        graph = gen.build_prompt_graph('she turns toward the door', REF)
        self.assertEqual(graph['5833_26']['inputs']['string'], original)
        self.assertGreater(len(original), 5000, 'the R2VA guide must be the real policy')

    def test_the_direction_lands_in_the_user_slot_only(self):
        direction = '  she turns toward the door and leaves  '
        graph = gen.build_prompt_graph(direction, REF)
        self.assertEqual(graph['5833_15']['inputs']['string'], direction)

    def test_the_reference_is_a_committed_asset_not_a_path(self):
        graph = gen.build_prompt_graph('walk on', REF)
        self.assertEqual(graph['5836']['inputs']['image'], REF)
        with self.assertRaisesRegex(ValueError, 'committed SDK asset'):
            gen.build_prompt_graph('walk on', '/home/user/ref.png')

    def test_one_reference_and_one_captured_output(self):
        graph = gen.build_prompt_graph('walk on', REF)
        batch = graph['5837']['inputs']
        # The installed batch node refuses fewer than two images; both slots
        # therefore carry the same committed reference.
        self.assertEqual(batch['inputcount'], 2)
        self.assertEqual(batch['image_1'], ['5836', 0])
        self.assertEqual(batch['image_2'], ['5836', 0])
        self.assertEqual(graph[gen.OUTPUT_NODE]['inputs']['text'], ['5833_6', 0])
        for node in (*gen.PREVIEW_NODES, *gen.UNUSED_NODES):
            self.assertNotIn(node, graph, f'{node} must not reach the job')

    def test_mode_and_input_validation(self):
        self.assertEqual(gen.build_prompt_graph('x', REF)['5833_28']['inputs']['choice'], 'rewrite')
        self.assertEqual(gen.build_prompt_graph('x', REF, mode='from-prompt')
                         ['5833_28']['inputs']['choice'], 'from-prompt')
        for bad in ('', '   ', None):
            with self.subTest(direction=bad), self.assertRaises(ValueError):
                gen.build_prompt_graph(bad, REF)
        with self.assertRaises(ValueError):
            gen.build_prompt_graph('x' * (gen.MAX_DIRECTION + 1), REF)
        with self.assertRaises(ValueError):
            gen.build_prompt_graph('x', REF, mode='invent')


if __name__ == '__main__':
    unittest.main()
