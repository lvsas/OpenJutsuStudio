"""What a continuation says to H3.

A continuation is not a new video: it must keep the character, the framing, the
light and the camera, and add what happens next. The R2VA format does the
opposite, so it is never used here.

When the operator writes nothing, the shot still has to move: the default below is
a real instruction, not an empty string that lets the model invent a new scene.
"""
from __future__ import annotations

DEFAULT_DIRECTION = 'the same action continues naturally, at the same pace'

SUBJECT = '<Subject 1> is the character shown in <Picture 1>, and must stay the same person.'


def continuation_prompt(direction: str, *, references: int = 1) -> str:
    """Build the sentence the continuity graph receives."""
    if not isinstance(direction, str):
        raise ValueError('A direction must be text')
    text = direction.strip() or DEFAULT_DIRECTION
    if len(text) > 4000:
        raise ValueError('A direction is limited to 4000 characters')
    # Operators write sentences with their own punctuation; appending another
    # period produced "shoulder.." and made the prompt look machine-mangled.
    text = text.rstrip(' .')
    lines = [f'Continue this shot: {text}.']
    if references:
        lines.append(SUBJECT)
    lines.append('Keep the same framing, the same lighting, the same camera movement '
                 'and the same background. Do not cut to a new shot.')
    return ' '.join(lines)
