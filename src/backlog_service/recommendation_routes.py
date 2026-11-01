"""Recommendation HTTP endpoints; human decisions are application use cases."""

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backlog_service.dependencies import Context, Recommendations
from backlog_service.domain import Recommendation

router = APIRouter(prefix="/projects/{project_id}/recommendations")


class RecommendationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["initial_backlog"]
    constraints: dict[str, Any] | None = None

    @field_validator("constraints")
    @classmethod
    def bounded(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value, allow_nan=False).encode()) > 4096:
            raise ValueError("Constraints exceed limit")
        return value


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1)


@router.post("", status_code=201, response_model=Recommendation)
def generate(
    draft: RecommendationDraft, context: Context, service: Recommendations
) -> Recommendation:
    return service.generate(context, draft.constraints)


@router.get("")
def list_recommendations(
    context: Context,
    service: Recommendations,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return service.list(context, limit, offset)


@router.get("/{recommendation_id}", response_model=Recommendation)
def get_recommendation(
    recommendation_id: UUID, context: Context, service: Recommendations
) -> Recommendation:
    return service.get(context, recommendation_id)


@router.post("/{recommendation_id}/approve", response_model=Recommendation)
def approve(
    recommendation_id: UUID, draft: Decision, context: Context, service: Recommendations
) -> Recommendation:
    return service.decide(context, recommendation_id, draft.expected_version, approve=True)


@router.post("/{recommendation_id}/reject", response_model=Recommendation)
def reject(
    recommendation_id: UUID, draft: Decision, context: Context, service: Recommendations
) -> Recommendation:
    return service.decide(context, recommendation_id, draft.expected_version, approve=False)
