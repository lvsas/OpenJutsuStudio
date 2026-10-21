"""The continuity compiler must publish its family with the node already installed.

The compiled record has always declared `family_assets_published: False,
requires_verified_family_publication: True`. This wires that known gap to
`OpenGenjutsuH3PublishClip` — no new node, the same one the Swap uses.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import h3_continuity_graphs as h3

REFERENCE = {'__type': 'core/ASSET', 'info': {'id': 'unit-reference'}}


def models():
    return h3.H3ContinuityModels(
        unet=h3.Weight('minimax_h3_fl2va_pruned_int8_convrot.safetensors'),
        clip=h3.Weight('qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'),
        video_vae=h3.Weight('minimax_h3_video_vae_fp16.safetensors'),
        audio_vae=h3.Weight('minimax_h3_audio_vae_fp32.safetensors'))


def root(publish_family=None):
    kwargs = {} if publish_family is None else {'publish_family': publish_family}
    return h3.build_h3_continuity('root', REFERENCE, 'continue the shot',
                                 operation_id='d' * 32, seed=7, width=1280, height=704,
                                 raw_frames=56, models=models(), **kwargs)


class PublicationWiringTests(unittest.TestCase):
    def test_publication_is_off_by_default_and_declared_as_missing(self):
        record = root().as_dict()
        self.assertNotIn('native_family', record['graph'])
        self.assertFalse(record['publication']['family_assets_published'])
        self.assertTrue(record['publication']['requires_verified_family_publication'])
        self.assertEqual(record['graph'][h3.HANDLE_NODE]['inputs']['text'], ['1216', 0])

    def test_publication_consumes_the_real_saver_clip_and_feeds_the_handle(self):
        record = root(publish_family=True).as_dict()
        graph = record['graph']
        self.assertEqual(graph['native_family'],
                         {'class_type': 'OpenGenjutsuH3PublishClip',
                          'inputs': {'clip': ['1216', 0]}})
        self.assertEqual(graph[h3.HANDLE_NODE]['inputs']['text'], ['native_family', 0])
        self.assertTrue(record['publication']['family_assets_published'])
        self.assertEqual(record['publication']['family_node'], 'native_family')

    def test_the_published_graph_still_satisfies_the_consumed_link_contract(self):
        # The contract runs on the compiled graph; appending the publisher must not
        # look like topology drift.
        graph = root(publish_family=True).graph
        h3.validate_consumed_links(graph)
        self.assertEqual(graph['native_family']['inputs']['clip'], ['1216', 0])

    def test_ambiguous_or_tampered_publication_is_refused(self):
        for value in ('yes', 1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                root(publish_family=value) if value is not None else h3.build_h3_continuity(
                    'root', REFERENCE, 'p', operation_id='d' * 32, seed=7, width=1280,
                    height=704, raw_frames=56, models=models(), publish_family=value)
        graph = root(publish_family=True).graph
        graph['native_family']['inputs']['clip'] = ['1488:1486', 1]
        with self.assertRaises(ValueError):
            h3.validate_consumed_links(graph)


if __name__ == '__main__':
    unittest.main()
