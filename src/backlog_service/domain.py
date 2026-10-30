import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

Priority = Literal["high", "medium", "low"]
Status = Literal["todo", "in_progress", "done"]


def trim_padding(value: object) -> object:
    # Match browser whitespace plus Python's separators; BOM is padding at the edges.
    return re.sub(r"^[\s\ufeff]+|[\s\ufeff]+$", "", value) if isinstance(value, str) else value


SearchText = Annotated[str, BeforeValidator(trim_padding), Field(max_length=200)]


class StoryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    acceptance_criteria: str = Field(default="", max_length=2000)
    priority: Priority = "medium"

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value: object) -> object:
        return trim_padding(value)


class StoryChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    acceptance_criteria: str | None = Field(default=None, max_length=2000)
    priority: Priority | None = None
    status: Status | None = None

    @field_validator("title", mode="before")
    @classmethod
    def trim_title(cls, value: object) -> object:
        return trim_padding(value)

    @model_validator(mode="after")
    def require_change(self) -> "StoryChange":
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("Provide at least one non-null editable field")
        return self


class Story(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)
    id: UUID
    project_id: UUID
    created_by: UUID
    title: str
    description: str
    acceptance_criteria: str
    priority: Priority
    status: Status
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_dates(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class StoryPage(BaseModel):
    items: list[Story]
    total: int
    limit: int
    offset: int
