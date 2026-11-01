"""Disabled-by-default local proposal; external producer contract is pending."""

from typing import Any

from fastapi import APIRouter

from backlog_service.dependencies import Context, ReviewEvents, ReviewGate
from backlog_service.domain import ReviewEvent

router = APIRouter()


@router.post("/projects/{project_id}/code-review/events")
def apply_event(
    gate: ReviewGate, draft: ReviewEvent, context: Context, service: ReviewEvents
) -> dict[str, Any]:
    return service.apply(context, draft)
