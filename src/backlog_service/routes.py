from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from backlog_service.dependencies import Context, Readiness, Service
from backlog_service.domain import (
    Priority,
    SearchText,
    Status,
    Story,
    StoryChange,
    StoryDraft,
    StoryPage,
)

router = APIRouter()


@router.post("/projects/{project_id}/stories", response_model=Story, status_code=201)
def create_story(draft: StoryDraft, context: Context, service: Service) -> Story:
    return service.create(context, draft)


@router.get("/projects/{project_id}/stories", response_model=StoryPage)
def list_stories(
    context: Context,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[SearchText, Query()] = "",
    status: Status | None = None,
    priority: Priority | None = None,
) -> StoryPage:
    return service.list(context, limit=limit, offset=offset, q=q, status=status, priority=priority)


@router.get("/projects/{project_id}/stories/{story_id}", response_model=Story)
def get_story(story_id: UUID, context: Context, service: Service) -> Story:
    story = service.get(context, story_id)
    if story is None:
        raise HTTPException(404, "Project unavailable")
    return story


@router.patch("/projects/{project_id}/stories/{story_id}", response_model=Story)
def update_story(story_id: UUID, change: StoryChange, context: Context, service: Service) -> Story:
    story = service.update(context, story_id, change)
    if story is None:
        raise HTTPException(404, "Project unavailable")
    return story


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
def ready(_readiness: Readiness) -> dict[str, str]:
    return {"status": "ready"}
