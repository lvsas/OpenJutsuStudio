"""Engine-owned prompt contracts for the public Edit brief."""
from __future__ import annotations

from dataclasses import dataclass

from config import RIPPLE_PROMPT

PROMPT_POLICY_VERSION = "character-recast-v1"


def _reference_instruction(count: int) -> str:
    if count == 1:
        action = "Replace the main person in the source frame with the character shown in the character reference image."
    else:
        action = "Recast the two main people in the source frame using the two supplied character reference images, one distinct character per person."
    return (
        "The first image is the source frame to edit; the additional images are character references, not scenes to reproduce. "
        f"{action} Use the references for character identity and appearance. "
        "Keep the source pose, expression, framing, lighting, background, and unrelated scene elements. "
        "Return one edited source frame, not a character sheet or collage."
    )


@dataclass(frozen=True)
class PromptProfile:
    """Translate a human brief only for a validated engine contract."""

    engine: str
    propagation_prompt: str

    def compose_frame_edit(
        self,
        edit_brief: str,
        legacy_target: str = "",
        reference_targets: list[str] | None = None,
        reference_count: int = 0,
    ) -> str:
        instruction = edit_brief.strip()
        target = legacy_target.strip()
        has_context = bool(target or any(hint.strip() for hint in reference_targets or ()))
        parts = [f"Target to change: {target}." if target else ""]
        parts.extend(
            f"Reference {index + 1} applies to: {hint.strip()}."
            for index, hint in enumerate(reference_targets or ())
            if hint.strip()
        )
        if reference_count:
            parts.insert(0, _reference_instruction(reference_count))
            if instruction:
                parts.append(f"Additional user direction (takes precedence over the default recast): {instruction}")
        else:
            parts.append(f"Requested edit: {instruction}" if has_context else instruction)
        return " ".join(part for part in parts if part)


PROMPT_PROFILES = {
    "ltx25-ripple": PromptProfile(
        engine="ltx25-ripple",
        propagation_prompt=RIPPLE_PROMPT,
    ),
}


def get_prompt_profile(engine: str) -> PromptProfile:
    try:
        return PROMPT_PROFILES[engine]
    except KeyError as exc:
        raise ValueError(f"No validated prompt profile for engine {engine!r}") from exc
