"""Item-scoped Module4 HTTP adapters; application owns authorization and state changes."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query

from backlog_service.dependencies import CodeReviews, Context
from backlog_service.module4_domain import CodeReview, ReviewRequest

router = APIRouter(prefix="/projects/{project_id}/items/{item_id}/code-reviews")


@router.post("", response_model=CodeReview, status_code=201)
def analyze(
    item_id: UUID, draft: ReviewRequest, context: Context, service: CodeReviews
) -> CodeReview:
    return service.analyze(context, item_id, draft)


@router.get("")
def list_reviews(
    item_id: UUID,
    context: Context,
    service: CodeReviews,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return service.list(context, item_id, limit, offset)


@router.get("/{review_id}", response_model=CodeReview)
def get_review(
    item_id: UUID, review_id: UUID, context: Context, service: CodeReviews
) -> CodeReview:
    return service.get(context, item_id, review_id)
