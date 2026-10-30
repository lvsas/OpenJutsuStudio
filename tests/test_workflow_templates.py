"""The tracked workflow files must exist, stay distinguishable, and keep their builder.

Two H3 graphs ship in this repository because they answer different questions:
a native take (with its MCTX capsule) and a full-latent continuation. They were
once both named "continuity", which invites editing the wrong one. These tests
pin the mapping so a rename or a copy-paste cannot make them interchangeable.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / 'workflows'
SRC = ROOT / 'src'

# file -> (builder module, expected node count, a node class only this graph may use)
TEMPLATES = {
    'h3-native-take.api.json': ('h3_continuity_graphs.py', 52, 'H3TrimAndSaveVideoWithMCtx'),
    'h3-continuity-latent.api.json': ('h3_latent_graphs.py', 83, 'H3JointConditioning'),
}


def nodes_of(path: Path) -> dict:
    body = json.loads(path.read_text())
    return body if all(key.isdigit() for key in body) else body.get('prompt', body)


class WorkflowTemplateMapping(unittest.TestCase):
    def test_each_template_exists_and_has_the_documented_size(self):
        for name, (_builder, count, _marker) in TEMPLATES.items():
            with self.subTest(template=name):
                path = WORKFLOWS / name
                self.assertTrue(path.is_file(), f'{name} is missing')
                self.assertEqual(len(nodes_of(path)), count,
                                 f'{name} changed size; update workflows/README.md')

    def test_each_template_carries_its_own_capability(self):
        for name, (_builder, _count, marker) in TEMPLATES.items():
            with self.subTest(template=name):
                classes = {node.get('class_type') for node in nodes_of(WORKFLOWS / name).values()}
                self.assertIn(marker, classes)

    def test_the_continuation_graph_adds_context_on_top_of_the_take(self):
        # The latent graph is a superset: it keeps the MCTX take machinery and adds
        # joint conditioning. The take graph must never grow continuation nodes,
        # otherwise the two paths would submit the same thing under different names.
        native = {node.get('class_type') for node in nodes_of(WORKFLOWS / 'h3-native-take.api.json').values()}
        latent = {node.get('class_type') for node in nodes_of(WORKFLOWS / 'h3-continuity-latent.api.json').values()}
        self.assertIn('H3MCtxApplyPins', native)
        self.assertIn('H3MCtxApplyPins', latent)
        self.assertIn('H3JointConditioning', latent)
        self.assertIn('H3ContextWindows', latent)
        self.assertNotIn('H3ContextWindows', native,
                         'the take graph must not carry continuation context windows')

    def test_each_template_is_referenced_by_exactly_one_builder(self):
        for name, (builder, _count, _marker) in TEMPLATES.items():
            with self.subTest(template=name):
                referenced = [path.name for path in SRC.glob('*.py')
                              if re.search(r"workflows/" + re.escape(name), path.read_text())]
                self.assertEqual(referenced, [builder],
                                 f'{name} must be compiled by {builder} only, found {referenced}')

    def test_readme_documents_both_templates(self):
        # These two are adopted graphs, not script exports: the README is the only
        # place that says which is which, so it has to stay true.
        readme = (WORKFLOWS / 'README.md').read_text()
        for name in TEMPLATES:
            self.assertIn(name, readme, f'{name} is not documented in workflows/README.md')


if __name__ == '__main__':
    unittest.main()
