"""Engine-owned prompt contracts for the public Edit brief."""
from __future__ import annotations

from dataclasses import dataclass

from config import RIPPLE_PROMPT


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
