"""Audit an API-format ComfyUI graph: reachability, dangling links, orphan outputs.

A node is only legitimate as a terminal if it is a real output node (the ones that
write to disk) or if its class is whitelisted as deliberately unused.
"""
import json
import sys
from pathlib import Path

OUTPUT_CLASSES = ('SaveVideo', 'SaveImage', 'SaveText', 'SaveAudio', 'PreviewImage',
                  'VHS_VideoCombine', 'SaveAnimatedWEBP', 'PreviewAudio', 'SAM3_TrackPreview',
                  # this pack saves the take together with its MCTX capsule
                  'H3TrimAndSaveVideoWithMCtx', 'H3JointRender')


# The vendor FLUX file keeps its layout-preview branch verbatim (25 -> 27 -> 26).
# We do not use that branch, but removing it would make us own a different topology
# than the published one, so it is allowed to end outside our live path.
VENDOR_ALLOWED = {'flux3-klein-official-t2i.json': {'25', '26', '27'}}


def links_in(value, nodes):
    """Yield every [node_id, slot] link, including inside Bundle/unbundle payloads."""
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
            yield value[0]
            return
        for item in value:
            yield from links_in(item, nodes)
    elif isinstance(value, dict):
        for item in value.values():
            yield from links_in(item, nodes)


def load(path):
    body = json.loads(Path(path).read_text())
    return body if all(k.isdigit() for k in body) else body.get('prompt', body)


def audit(path, allow_unused=()):
    nodes = load(path)
    is_template = Path(path).name.endswith('.template.json')
    problems = []
    consumed = set()
    produced = set()
    for nid, node in nodes.items():
        produced.add(nid)
        for value in node.get('inputs', {}).values():
            for link in links_in(value, nodes):
                if link in nodes:
                    consumed.add(link)
                elif link.isdigit():
                    problems.append(f'dangling: node {nid} -> {link} (absent)')

    terminals = [nid for nid, node in nodes.items()
                 if node.get('class_type') in OUTPUT_CLASSES and nid not in consumed]
    if not terminals and not is_template:
        problems.append('no terminal output node')

    # reachability backwards from terminals
    reachable = set()
    stack = list(terminals)
    while stack:
        nid = stack.pop()
        if nid in reachable:
            continue
        reachable.add(nid)
        for value in nodes[nid].get('inputs', {}).values():
            for link in links_in(value, nodes):
                if link in nodes:
                    stack.append(link)

    orphans = sorted(set(nodes) - reachable, key=lambda x: (len(x), x))
    allowed = {nid for nid in orphans if nodes[nid].get('class_type') in allow_unused}
    allowed |= {nid for nid in orphans if nid in VENDOR_ALLOWED.get(Path(path).name, set())}
    real_orphans = [] if is_template else [nid for nid in orphans if nid not in allowed]

    return {
        'file': Path(path).name,
        'template': is_template,
        'nodes': len(nodes),
        'terminals': [(nid, nodes[nid].get('class_type')) for nid in terminals],
        'orphans': [(nid, nodes[nid].get('class_type')) for nid in real_orphans],
        'allowed_orphans': [(nid, nodes[nid].get('class_type')) for nid in allowed],
        'dangling': problems,
    }


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    files = sys.argv[1:] or sorted(str(p) for p in (root / 'workflows').glob('*.json'))
    bad = 0
    for f in files:
        r = audit(f)
        print(f"{r['file']}: {r['nodes']} nodes, terminals {len(r['terminals'])}, "
              f"orphans {len(r['orphans'])}, dangling {len(r['dangling'])}")
        for nid, cls in r['orphans']:
            print(f"    ORPHAN {nid} {cls}")
        for nid, cls in r['allowed_orphans']:
            print(f"    allowed-unused {nid} {cls}")
        for d in r['dangling']:
            print(f"    {d}")
        bad += len(r['orphans']) + len(r['dangling'])
    sys.exit(1 if bad else 0)
