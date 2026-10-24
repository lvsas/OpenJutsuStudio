"""Bounded, path-free timeline API inputs (frame ranges are end-exclusive)."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{32}$")]
Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=160)]
Revision = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
Frame = Annotated[int, Field(strict=True, ge=0, le=10_000_000)]
MAX_CLIPS = 256
MAX_KNOWN_CLIPS = 2048


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProject(Payload):
    title: Title
    character_id: Identifier | None = None


class Placement(Payload):
    clip_id: Identifier
    in_frame: Frame
    out_frame: Frame

    @model_validator(mode="after")
    def ordered(self):
        if self.in_frame >= self.out_frame:
            raise ValueError("Frame range must be nonempty and end-exclusive")
        return self


class EditProject(Payload):
    revision: Revision
    title: Title | None = None
    clips: Annotated[list[Placement], Field(max_length=MAX_CLIPS)]

    @model_validator(mode="after")
    def unique(self):
        if len({clip.clip_id for clip in self.clips}) != len(self.clips):
            raise ValueError("Clip IDs must be unique")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("Title cannot be null")
        return self


class ImportJob(Payload):
    revision: Revision
    job_id: Identifier


class ExportProject(Payload):
    revision: Revision


class NativePlacement(Payload):
    placement_id: Identifier
    take_id: Identifier


class NativeDraft(Payload):
    prompt: Annotated[str, StringConstraints(strict=True, max_length=4000)]
    seed: Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9]*$")]
    raw_frames: Annotated[int, Field(strict=True, ge=5, le=3600)] = 277

    @model_validator(mode="after")
    def bounded(self):
        # Compare decimal strings: never round a uint64 through a JS-sized float
        # or parse unbounded user input as a Python integer. Preserve the input.
        significant = self.seed.lstrip("0")
        if len(significant) > 20 or (len(significant) == 20 and significant > "18446744073709551615"):
            raise ValueError("Seed must be empty or a decimal uint64")
        if (self.raw_frames - 5) % 17:
            raise ValueError("Raw frames must lie on the H3 17k+5 grid")
        return self


PositionKey = Annotated[str, StringConstraints(strict=True,
    pattern=r"^(root|forward|prepend|bridge):(start|[0-9a-f]{32}):(end|[0-9a-f]{32})$")]


def position_is_current(key, placements):
    mode, left, right = key.split(':')
    ids = [p.placement_id if hasattr(p, 'placement_id') else p['placement_id'] for p in placements]
    pairs = list(zip(['start'] + ids, ids + ['end']))
    inferred = 'root' if not ids else 'prepend' if left == 'start' else 'forward' if right == 'end' else 'bridge'
    return (left, right) in pairs and mode in ('root', inferred)


class PositionDraft(NativeDraft):
    mode: Literal['root', 'forward', 'prepend', 'bridge']
    reference_ids: list[Identifier] = Field(default_factory=list)
    reference_mode: Literal['inherit', 'custom'] = 'inherit'
    width: Annotated[int, Field(strict=True, ge=32, le=2048)] = 1024
    height: Annotated[int, Field(strict=True, ge=32, le=2048)] = 576
    count: Annotated[int, Field(strict=True, ge=1, le=4)] = 1

    @model_validator(mode='after')
    def aligned(self):
        if self.width % 32 or self.height % 32:
            raise ValueError('Picture size must be aligned to 32')
        return self


class EditNativeWorkspace(Payload):
    revision: Revision
    placements: Annotated[list[NativePlacement], Field(max_length=MAX_CLIPS)]
    selected_placement_id: Identifier | None
    drafts: dict[Identifier, NativeDraft]
    title: Title | None = None
    selected_position: PositionKey | None = None
    position_drafts: Annotated[dict[PositionKey, PositionDraft], Field(max_length=MAX_KNOWN_CLIPS)] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self):
        ids = {placement.placement_id for placement in self.placements}
        if len(ids) != len(self.placements):
            raise ValueError("Placement IDs must be unique")
        if self.selected_placement_id is not None and self.selected_placement_id not in ids:
            raise ValueError("Selected placement must belong to this workspace")
        if not self.drafts.keys() <= ids:
            raise ValueError("Drafts must belong to placements present in this workspace")
        if any(key.split(':')[0] != draft.mode for key, draft in self.position_drafts.items()):
            raise ValueError('Position draft mode must match its key')
        if self.selected_position is not None and (
                self.selected_position not in self.position_drafts
                or not position_is_current(self.selected_position, self.placements)):
            raise ValueError('Choose a current position with a saved draft')
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("Title cannot be null")
        return self
