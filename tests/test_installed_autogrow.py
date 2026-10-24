"""Installed V3 autogrow variants; metadata-only tests, no node execution."""
import copy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from readiness import _inventory
import h3_continuity_graphs as h3


class InstalledAutogrowTests(unittest.TestCase):
    def setUp(self):
        # Shape observed on the installed stock ComfyMathExpression: named members,
        # not a numbered prefix/max. Model/reference menus are not synthesized here.
        self.spec = ['COMFY_AUTOGROW_V3', {'template': {
            'names': list('abcdefghijklmnopqrstuvwxyz'), 'min': 1,
            'input': {'required': {'value': ['FLOAT,INT,BOOLEAN', {}]}},
        }}]
        self.info = {'ComfyMathExpression': {'input': {'required': {'expression': ['STRING', {}]},
                     'optional': {'values': self.spec}}, 'output': ['FLOAT']}}
        self.graph = {'1': {'class_type': 'ComfyMathExpression',
                           'inputs': {'expression': 'a+1', 'values.a': 7}}}

    def test_named_members_need_no_prefix_or_max_in_both_consumers(self):
        original = copy.deepcopy((self.info, self.graph))
        self.assertEqual(_inventory(self.info, self.graph), ([], []))
        # Topology has its own pinned full-graph tests; isolate installed-field resolution here.
        with patch.object(h3, "validate_consumed_links"):
            h3.validate_graph_contracts(self.graph, self.info)
        self.assertEqual((self.info, self.graph), original)

    def test_named_member_is_exact_and_unknown_names_fail_closed(self):
        for member in ['aa', 'a0', 'A', '', '../a']:
            with self.subTest(member=member):
                graph = copy.deepcopy(self.graph)
                graph['1']['inputs'] = {'expression': 'a+1', 'values.' + member: 7}
                with self.assertRaises(ValueError):
                    _inventory(self.info, graph)
                with patch.object(h3, "validate_consumed_links"), self.assertRaises(ValueError):
                    h3.validate_graph_contracts(graph, self.info)

    def test_numbered_capacity_and_malformed_schema_remain_strict(self):
        spec = ['COMFY_AUTOGROW_V3', {'template': {'prefix': 'image_', 'min': 0, 'max': 2,
                 'input': {'required': {'image': ['IMAGE', {}]}}}}]
        info = {'Dynamic': {'input': {'optional': {'refs': spec}}, 'output': ['IMAGE']}}
        for member, valid in [('image_0', True), ('image_1', True), ('image_2', False),
                              ('image_-1', False), ('image_01', False), ('other_0', False)]:
            with self.subTest(member=member):
                graph = {'1': {'class_type': 'Dynamic', 'inputs': {'refs.' + member: 'synthetic'}}}
                if valid:
                    self.assertEqual(_inventory(info, graph), ([], []))
                else:
                    with self.assertRaises(ValueError):
                        _inventory(info, graph)
        broken = copy.deepcopy(self.info)
        broken['ComfyMathExpression']['input']['optional']['values'][1]['template'] = {}
        with self.assertRaises(ValueError):
            _inventory(broken, self.graph)
