"""Bounded, path-free timeline API inputs (frame ranges are end-exclusive)."""
from typing import Annotated
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
