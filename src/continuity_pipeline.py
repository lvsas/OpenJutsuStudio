"""Turn a stored Take into a validated native parent, or refuse it.

The continuity compiler demands a parent whose geometry, fps and effective
weights match the target, and whose delivered range can actually carry the pin
window. A Take shorter than that window cannot be continued from its tail; the
refusal has to happen before any upload or GPU work.
"""
from __future__ import annotations

from pathlib import Path

from continuable_take import get_take, get_validated_family
from h3_continuity_graphs import H3ContinuityModels, NativeH3Parent, PIN_WINDOW


def native_parent(take, artifacts, *, models, clip):
    """Build the attestation from measured facts, refusing an unusable parent.

    ``take`` is the frozen record, ``artifacts`` the freshly validated family and
    ``clip`` the loader literal the target returned after restaging. Nothing here
    trusts a filename convention or a caller-supplied geometry.
    """
    if not isinstance(models, H3ContinuityModels):
        raise ValueError('A complete continuity model profile is required')
    context = artifacts.to_manifest()['context']
    delivered = context['delivered_frames']
    if delivered < PIN_WINDOW:
        raise ValueError(
            f'This take delivers {delivered} frames; a tail pin needs at least {PIN_WINDOW}')
    if context['fps'] != 24:
        raise ValueError('Native continuation currently requires a 24 fps take')
    return NativeH3Parent(take_id=take.take_id, clip=clip, width=context['width'],
                          height=context['height'], delivered_frames=delivered, fps=24,
                          models=models, capsule_digest=take.capsule_sha256)


def parent_from_registry(work: str | Path, take_id: str, *, models, clip):
    """Re-validate the stored family, then build the parent attestation."""
    take = get_take(work, take_id)
    artifacts = get_validated_family(work, take_id)
    return native_parent(take, artifacts, models=models, clip=clip)
