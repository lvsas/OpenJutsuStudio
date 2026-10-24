"""Ordered-reference root compiler on the pinned native continuity graph.

Pure CPU compilation only: no SDK uploads, submission, rendering or publication
verification. The original reference route stays intact; additional images use
MiniMaxH3ReferenceToVideo's native autogrow sockets. No product reference cap is
introduced here; installed target capacity remains a separate preflight gate.
"""
from __future__ import annotations

import copy

import h3_continuity_graphs as continuity
from h3_continuity_graphs import ContinuityRecipe


_REFERENCE_NODE = '797'
_REFERENCE_PREFIX = 'ref_images.ref_image_'


def _loader_id(index):
    return f'root_reference_{index}'


def _expand_references(graph, references):
    """Only append slots 1..N-1; slot zero retains its pinned bundle route."""
    for index, reference in enumerate(references[1:], start=1):
        node = _loader_id(index)
        if node in graph:
            raise ValueError('Root reference loader collides with the pinned graph')
        graph[node] = {'class_type': 'LoadImage', 'inputs': {'image': reference}}
        graph[_REFERENCE_NODE]['inputs'][f'{_REFERENCE_PREFIX}{index}'] = [node, 0]


def _validate_expansion(graph, *, base_graph, references, metadata):
    """Contract ONLY the declared additions, then reapply the global validator.

    Never teach validate_consumed_links to accept arbitrary dynamic topology.
    Every added loader/socket must match the ordered committed reference exactly;
    all other controls, links and nodes must equal the already validated base.
    """
    contracted = copy.deepcopy(graph)
    try:
        for index, reference in enumerate(references[1:], start=1):
            node = _loader_id(index)
            if contracted.pop(node) != {'class_type': 'LoadImage',
                                        'inputs': {'image': reference}}:
                raise ValueError('Root reference loader differs from its committed asset')
            field = f'{_REFERENCE_PREFIX}{index}'
            if contracted[_REFERENCE_NODE]['inputs'].pop(field) != [node, 0]:
                raise ValueError('Root reference autogrow link differs from its ordered slot')
        if contracted['1216']['inputs']['metadata'] != metadata:
            raise ValueError('Root saver metadata differs from the immutable recipe')
        contracted['1216']['inputs']['metadata'] = base_graph['1216']['inputs']['metadata']
    except (KeyError, TypeError) as exc:
        raise ValueError('Corrupted root reference expansion') from exc
    if contracted != base_graph:
        raise ValueError('Root expansion changed the pinned base outside reference additions')
    continuity.validate_consumed_links(contracted)
    if continuity.unconsumed_nodes(graph):
        raise ValueError('Root expansion contains unconsumed nodes')
    continuity.canonical_digest(graph)  # finite strict JSON, including additions


def build_h3_root(*, references, prompt, operation_id, seed, width, height,
                  raw_frames, models, publish_family=True) -> ContinuityRecipe:
    """Freeze a parentless native root from an ordered, nonempty SDK asset set.

    All model, operation, prompt, uint64, geometry and native-grid validation is
    delegated to the existing compiler (including its strict bool rejection).
    ``reference`` remains the first asset for existing recipe readers, while
    ``references`` and saver metadata carry the complete ordered set. Publication
    metadata describes graph wiring, not evidence that files were rendered.
    """
    if not isinstance(references, (list, tuple)) or not references:
        raise ValueError('Root references must be an ordered nonempty list or tuple of committed SDK assets')
    references = [continuity._reference(reference) for reference in references]
    base = continuity.build_h3_continuity(
        'root', references[0], prompt, operation_id=operation_id, seed=seed,
        width=width, height=height, raw_frames=raw_frames, models=models,
        parents=(), publish_family=publish_family)
    base_graph = base.graph
    # Validate the pinned base INCLUDING the optional publication hop before
    # making any bounded additions. A corrupt template cannot be expanded away.
    continuity.validate_consumed_links(base_graph)
    record = base.as_dict()
    record.pop('graph')
    record.pop('graph_digest')
    publication = record.pop('publication')
    record['references'] = references
    metadata = continuity._canonical(record)
    graph = copy.deepcopy(base_graph)
    _expand_references(graph, references)
    graph['1216']['inputs']['metadata'] = metadata
    _validate_expansion(graph, base_graph=base_graph, references=references,
                        metadata=metadata)
    record.update(graph=graph, graph_digest=continuity.canonical_digest(graph),
                  publication=publication)
    return ContinuityRecipe(continuity._canonical(record))
