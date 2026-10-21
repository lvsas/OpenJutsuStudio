"""Strict browser-facing input for a native continuation request.

The client names an intention: which prompt, which explicit seed, how many native
frames. It never supplies a graph, a filesystem path, a compute target or a
backend choice — those stay server-side and are frozen before submission.

`request_id` is only the client's de-duplication key. It is not an operation ID
and it never selects a filesystem location.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

# The native H3 sampler consumes a 17k+5 frame grid at 24 fps. This bound is
# specific to the H3 Forward path; LTX and image adapters must not reuse it.
H3_FRAME_GRID_OFFSET = 5
H3_FRAME_GRID_STEP = 17


class ForwardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    # An empty direction is legitimate: the shot must still move, and the server
    # supplies a real continuation instruction instead of letting the model invent.
    prompt: str = Field(default='', max_length=4000)
    seed: StrictInt = Field(ge=0, le=(1 << 64) - 1)
    raw_frames: StrictInt = Field(ge=5, le=3600)


    @field_validator("raw_frames")
    @classmethod
    def native_h3_grid(cls, value: int) -> int:
        if (value - H3_FRAME_GRID_OFFSET) % H3_FRAME_GRID_STEP:
            raise ValueError("H3 frames must follow the native 17k+5 grid")
        return value
