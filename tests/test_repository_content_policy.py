"""What ships must not name an adapter the product does not ship.

The contest repository is public. A workflow that merely *mentions* a style LoRA
is a rule problem even when the switch is off and the file is never loaded: the
graph is read by people, and an NSFW adapter name in a shipped graph is
disqualifying. This guard is repository-wide so the mention cannot come back
through a re-export, a doc or a fixture.
"""
import json
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Every LoRA a shipped graph may name. Adding one is a product decision: it is
# installed on the target, audited for the contest and listed in dependencies.json.
ALLOWED_LORAS = {
    'H3/h3_character_swap_v1.5.safetensors',                        # Swap identity
    'minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors',  # H3 speed
    'LTX25_Ripple_v11.safetensors',                                 # LTX identity
}
SKIP_DIRS = {'.git', '.venv', 'work', 'cache', 'dist', 'node_modules', '__pycache__'}
TEXT_SUFFIXES = {'.py', '.js', '.mjs', '.json', '.md', '.html', '.css',
                 '.yaml', '.yml', '.sh', '.txt'}
# Family names of adult adapters that must never appear in a submitted file.
# Written in fragments so this guard does not match its own source and cannot be
# satisfied by editing one literal.
_FAMILIES = ('mys' 'tic', 'foot' 'job', 'sex' 'god', 'deep' 'throat',
             'hm' 'pussy', 'vag' 'assist', 'nsfw[_ -]?anime')
FORBIDDEN_ADAPTERS = re.compile('|'.join(_FAMILIES), re.I)


def _shipped_files():
    for path in ROOT.rglob('*'):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


class ShippedWorkflowPolicyTests(unittest.TestCase):
    def test_shipped_workflows_only_name_audited_adapters(self):
        found = {}
        for path in sorted((ROOT / 'workflows').glob('*.json')):
            graph = json.loads(path.read_text())
            for node_id, node in graph.items():
                if not isinstance(node, dict) or node.get('class_type') != 'LoraLoaderModelOnly':
                    continue
                name = (node.get('inputs') or {}).get('lora_name')
                if isinstance(name, str):
                    found.setdefault(name, []).append(f'{path.name}:{node_id}')
        self.assertEqual({}, {name: where for name, where in found.items()
                              if name not in ALLOWED_LORAS},
                         'A shipped workflow names a LoRA this product does not audit')

    def test_no_shipped_file_names_an_adult_adapter_family(self):
        offenders = [str(path.relative_to(ROOT)) for path in _shipped_files()
                     if FORBIDDEN_ADAPTERS.search(path.read_text(errors='ignore'))]
        self.assertEqual([], offenders,
                         'A submitted file mentions an adapter this product must not ship')


if __name__ == '__main__':
    unittest.main()
