"""The prompt job runs exactly as the authored workflow does."""
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import h3_prompt_generator as gen  # noqa: E402

REF1 = {'__type': 'core/ASSET', 'info': {'id': 'ref-one'}}
REF2 = {'__type': 'core/ASSET', 'info': {'id': 'ref-two'}}


class PromptGraphTests(unittest.TestCase):
    def test_the_authored_guide_is_copied_byte_for_byte(self):
        original = json.loads(gen.TEMPLATE.read_text())['5833_26']['inputs']['string']
        graph = gen.build_prompt_graph('she walks on', REF1)
        self.assertEqual(graph['5833_26']['inputs']['string'], original)
        self.assertGreater(len(original), 5000, 'the R2VA guide must be the real policy')

    def test_the_default_mode_is_the_authored_from_prompt(self):
        self.assertEqual(gen.build_prompt_graph('x', REF1)['5833_28']['inputs']['choice'],
                         'from-prompt')

    def test_the_operator_words_are_carried_untouched(self):
        graph = gen.build_prompt_graph('  she turns to the door.  ', REF1)
        self.assertEqual(graph['5833_15']['inputs']['string'], 'she turns to the door.')

    def test_an_empty_direction_is_legitimate(self):
        graph = gen.build_prompt_graph('', REF1)
        self.assertEqual(graph['5833_15']['inputs']['string'], '')

    def test_one_reference_fills_both_batch_slots(self):
        graph = gen.build_prompt_graph('x', REF1)
        batch = graph['5837']['inputs']
        self.assertEqual(batch['inputcount'], 2)
        self.assertEqual(batch['image_1'], ['5836', 0])
        self.assertEqual(batch['image_2'], ['5836', 0])

    def test_several_references_are_all_attached_in_order(self):
        graph = gen.build_prompt_graph('x', [REF1, REF2])
        batch = graph['5837']['inputs']
        self.assertEqual(batch['inputcount'], 2)
        self.assertEqual(batch['image_1'], ['5836', 0])
        self.assertEqual(batch['image_2'], ['5836_2', 0])
        self.assertEqual(graph['5836_2']['inputs']['image'], REF2)

    def test_the_produced_text_is_captured_not_previewed(self):
        graph = gen.build_prompt_graph('x', REF1)
        self.assertEqual(graph[gen.OUTPUT_NODE]['inputs']['text'], ['5833_6', 0])
        for node in (*gen.PREVIEW_NODES, *gen.UNUSED_NODES):
            self.assertNotIn(node, graph, f'{node} must not reach the job')

    def test_a_reference_must_be_a_committed_asset(self):
        with self.assertRaisesRegex(ValueError, 'committed SDK asset'):
            gen.build_prompt_graph('x', '/home/user/ref.png')

    def test_inputs_are_validated(self):
        with self.assertRaises(ValueError):
            gen.build_prompt_graph('x', [])
        with self.assertRaises(ValueError):
            gen.build_prompt_graph('x' * (gen.MAX_DIRECTION + 1), REF1)
        with self.assertRaises(ValueError):
            gen.build_prompt_graph(None, REF1)
        with self.assertRaises(ValueError):
            gen.build_prompt_graph('x', REF1, mode='invent')


if __name__ == '__main__':
    unittest.main()
