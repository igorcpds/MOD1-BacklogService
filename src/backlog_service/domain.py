import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

Priority = Literal["high", "medium", "low"]
Status = Literal["todo", "in_progress", "done"]


class InsufficientProjectPermissions(Exception):
    pass


@dataclass(frozen=True)
class ProjectContext:
    """Request snapshot built only after current project access has been confirmed."""

    project_id: UUID
    actor_id: UUID
    permissions: frozenset[str]
    project_status: str = "active"
    archived: bool = False

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise InsufficientProjectPermissions("Insufficient project permissions")


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


class Conflict(Exception):
    pass


class MissingItem(Exception):
    pass


class DependencyUnavailable(Exception):
    pass


Kind = Literal["story", "epic", "task"]
MoSCoW = Literal["must", "should", "could", "wont"]


def valid_estimate(value: str | None) -> str | None:
    from decimal import Decimal, InvalidOperation

    if value is None:
        return None
    try:
        number = Decimal(value)
        if (
            not number.is_finite()
            or number < 0
            or number > 1000000
            or number != number.quantize(Decimal("0.0001"))
        ):
            raise ValueError("Invalid estimate")
        return format(number, "f")
    except InvalidOperation:
        raise ValueError("Invalid estimate") from None


class ItemDraft(StoryDraft):
    @field_validator("epic_id", "parent_story_id", "assignee_id", mode="before", check_fields=False)
    @classmethod
    def identifiers(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    kind: Kind = "story"
    persona: str = Field(default="", max_length=500)
    action: str = Field(default="", max_length=500)
    benefit: str = Field(default="", max_length=500)
    guided: bool = False
    epic_id: UUID | None = None
    parent_story_id: UUID | None = None
    moscow_priority: MoSCoW | None = None
    estimate_value: str | None = Field(default=None, max_length=32)
    estimate_unit: Literal["points", "hours"] | None = None
    assignee_id: UUID | None = None
    is_blocked: bool = False
    blocked_reason: str = Field(default="", max_length=1000)

    @field_validator("estimate_value")
    @classmethod
    def estimate(cls, value: str | None) -> str | None:
        return valid_estimate(value)

    @model_validator(mode="after")
    def coherent(self) -> "ItemDraft":
        if self.guided and not all(v.strip() for v in (self.persona, self.action, self.benefit)):
            raise ValueError("Guided fields required")
        if (self.estimate_value is None) != (self.estimate_unit is None):
            raise ValueError("Estimate requires value and unit")
        if self.is_blocked and not self.blocked_reason.strip():
            raise ValueError("Blocked reason required")
        if self.epic_id and self.kind != "story" or self.parent_story_id and self.kind != "task":
            raise ValueError("Invalid parent kind")
        return self


class ItemChange(BaseModel):
    @field_validator("epic_id", "parent_story_id", "assignee_id", mode="before", check_fields=False)
    @classmethod
    def identifiers(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    title: str = Field(default="", min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    acceptance_criteria: str = Field(default="", max_length=2000)
    priority: Priority = "medium"
    status: Status = "todo"
    persona: str = Field(default="", max_length=500)
    action: str = Field(default="", max_length=500)
    benefit: str = Field(default="", max_length=500)
    guided: bool = False
    epic_id: UUID | None = None
    parent_story_id: UUID | None = None
    moscow_priority: MoSCoW | None = None
    estimate_value: str | None = Field(default=None, max_length=32)
    estimate_unit: Literal["points", "hours"] | None = None
    assignee_id: UUID | None = None
    is_blocked: bool = False
    blocked_reason: str = Field(default="", max_length=1000)
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("title", mode="before")
    @classmethod
    def title_trim(cls, value: object) -> object:
        return trim_padding(value)

    @field_validator("estimate_value")
    @classmethod
    def estimate(cls, value: str | None) -> str | None:
        return valid_estimate(value)

    @model_validator(mode="after")
    def nonempty(self) -> "ItemChange":
        if not self.model_fields_set - {"expected_version"}:
            raise ValueError("Provide editable fields")
        return self


class Item(Story):
    @field_validator("epic_id", "parent_story_id", "assignee_id", mode="before", check_fields=False)
    @classmethod
    def identifiers(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    kind: Kind = "story"
    persona: str = ""
    action: str = ""
    benefit: str = ""
    guided: bool = False
    epic_id: UUID | None = None
    parent_story_id: UUID | None = None
    moscow_priority: MoSCoW | None = None
    estimate_value: str | None = Field(default=None, max_length=32)
    estimate_unit: Literal["points", "hours"] | None = None
    assignee_id: UUID | None = None
    is_blocked: bool = False
    blocked_reason: str = ""
    version: int = 1
    position: int = 0
    assignee_available: bool | None = None


class ItemPage(BaseModel):
    items: list[Item]
    total: int
    limit: int
    offset: int


class ReorderGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Status | None = None
    moscow_priority: MoSCoW | None = None


class Reorder(BaseModel):
    @field_validator("item_ids", mode="before", check_fields=False)
    @classmethod
    def identifiers(cls, value: object) -> object:
        return (
            [UUID(item) if isinstance(item, str) else item for item in value]
            if isinstance(value, list)
            else value
        )

    model_config = ConfigDict(extra="forbid", strict=True)
    item_ids: list[UUID] = Field(min_length=1, max_length=5000)
    expected_version: int = Field(ge=0)
    group: ReorderGroup | None = None


class SuggestedStory(ItemDraft):
    kind: Literal["story"] = "story"

    @model_validator(mode="after")
    def no_external_references(self) -> "SuggestedStory":
        if self.epic_id or self.parent_story_id or self.assignee_id:
            raise ValueError("Initial suggestions cannot invent source IDs")
        return self


class GeneratedProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1, max_length=2000)
    justification: str = Field(min_length=1, max_length=4000)
    evidence: list[str] = Field(min_length=1, max_length=50)
    suggestions: list[SuggestedStory] = Field(min_length=1, max_length=50)

    @field_validator("evidence")
    @classmethod
    def bounded_evidence(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 200 for value in values):
            raise ValueError("Invalid evidence")
        return values


class Recommendation(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)
    id: UUID
    project_id: UUID
    created_by: UUID
    kind: Literal["initial_backlog"] = "initial_backlog"
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    version: int = 1
    created_at: datetime
    model: str
    provider: str
    simulated: bool
    summary: str
    justification: str
    evidence: list[str]
    suggestions: list[dict[str, object]]
    context_version: str
    applied_item_ids: list[UUID] = Field(default_factory=list)

    @field_validator("created_at")
    @classmethod
    def utc_date(cls, value: datetime) -> datetime:
        return Story.utc_dates(value)


@dataclass(frozen=True)
class ReviewPrincipal:
    name: str
    project_ids: frozenset[UUID]


class ReviewEvent(BaseModel):
    """Local proposed ingress schema; actual producer agreement is pending."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    schema_version: Literal[1]
    event_id: UUID
    project_id: UUID
    item_id: UUID
    event_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    occurred_at: datetime
    expected_item_version: int = Field(ge=1)

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_schema(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Unsupported event schema")
        return value

    @field_validator("event_id", "project_id", "item_id", mode="before")
    @classmethod
    def identifiers(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    @field_validator("occurred_at", mode="before")
    @classmethod
    def timestamp(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("occurred_at")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Event timestamp must include timezone")
        return value.astimezone(UTC)
