"""Geometry for a continuation: the parent's ratio, a budget that adapts.

A swap can produce any ratio, so the continuity path must not assume 16:9 or a
fixed megapixel target. What must hold:

* the aspect ratio stays the parent's, within a rounding tolerance;
* both sides are multiples of the model's pixel block, so nothing is resampled;
* the area never exceeds the budget, because generation cost follows it.
"""
from __future__ import annotations

import math

BLOCK = 32
MAX_MEGAPIXELS = 1.0
RATIO_TOLERANCE = 0.02


def continuity_geometry(width: int, height: int, *, block: int = BLOCK,
                        max_megapixels: float = MAX_MEGAPIXELS) -> tuple[int, int]:
    """Return the (width, height) a continuation should use."""
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError('A positive integer source geometry is required')
    if type(block) is not int or block <= 0:
        raise ValueError('A positive pixel block is required')
    if not isinstance(max_megapixels, (int, float)) or max_megapixels <= 0:
        raise ValueError('A positive megapixel budget is required')

    # Already conformant and within budget: change nothing.
    if width % block == 0 and height % block == 0 and width * height <= max_megapixels * 1_000_000:
        return width, height

    ratio = width / height
    budget = max_megapixels * 1_000_000
    # A continuation of a bigger source is scaled down to the budget, keeping the
    # ratio; a smaller one keeps its size.
    scale = min(1.0, math.sqrt(budget / (width * height)))
    base = width * scale

    # Among the candidates whose ratio is acceptable, keep the one that uses the
    # budget best: an exact ratio that throws away a third of the pixels is worse
    # than a 0.3% ratio error at full size.
    target_area = min(budget, width * height)
    best = None
    for step in range(-6, 7):
        candidate_w = int(round((base / block) + step)) * block
        if candidate_w < block:
            continue
        candidate_h = int(round(candidate_w / ratio / block)) * block
        if candidate_h < block:
            continue
        if candidate_w * candidate_h > budget:
            continue
        error = abs(math.log((candidate_w / candidate_h) / ratio))
        if error > RATIO_TOLERANCE:
            continue
        area_gap = abs(candidate_w * candidate_h - target_area)
        score = (area_gap, error)
        if best is None or score < best[0]:
            best = (score, candidate_w, candidate_h)

    if best is None:
        raise ValueError('No geometry fits the budget at this block size')
    _, chosen_w, chosen_h = best
    if abs(math.log((chosen_w / chosen_h) / ratio)) > RATIO_TOLERANCE:
        raise ValueError('The source ratio cannot be kept at this block size')
    return chosen_w, chosen_h
