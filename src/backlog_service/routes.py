from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backlog_service.domain import (
    Priority,
    SearchText,
    Status,
    Story,
    StoryChange,
    StoryDraft,
    StoryPage,
)
from backlog_service.models import StoryRecord
from backlog_service.project_access import ProjectsUnavailable, ProjectUnavailable
from backlog_service.repository import StoryRepository
from backlog_service.security import AuthenticationRejected, SigningKeysUnavailable
from backlog_service.service import StoriesService

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    actor_id: UUID
    token: str = field(repr=False)


@dataclass(frozen=True)
class ProjectContext:
    project_id: UUID
    actor_id: UUID
    permissions: frozenset[str]

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise HTTPException(403, "Insufficient project permissions")


def unauthorized() -> HTTPException:
    return HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})


def current_principal(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Principal:
    if credentials is None:
        raise unauthorized()
    try:
        actor: UUID = request.app.state.verifier.verify(credentials.credentials)
        return Principal(actor, credentials.credentials)
    except AuthenticationRejected:
        raise unauthorized() from None
    except SigningKeysUnavailable:
        raise HTTPException(503, "Service temporarily unavailable") from None


def authorized_project(
    project_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> ProjectContext:
    try:
        permissions = request.app.state.project_access.require_access(
            project_id, principal.actor_id, principal.token
        )
    except ProjectUnavailable:
        raise HTTPException(404, "Project unavailable") from None
    except AuthenticationRejected:
        raise unauthorized() from None
    except ProjectsUnavailable:
        raise HTTPException(503, "Service temporarily unavailable") from None
    return ProjectContext(project_id, principal.actor_id, permissions)


Context = Annotated[ProjectContext, Depends(authorized_project)]


def story_service(request: Request, context: Context) -> Iterator[StoriesService]:
    with Session(request.app.state.engine, expire_on_commit=False) as session:
        yield StoriesService(StoryRepository(session))


Service = Annotated[StoriesService, Depends(story_service)]


@router.post("/projects/{project_id}/stories", response_model=Story, status_code=201)
def create_story(draft: StoryDraft, context: Context, service: Service) -> Story:
    context.require("backlog:create")
    return service.create(context.project_id, context.actor_id, draft)


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
    context.require("backlog:read")
    return service.list(
        context.project_id, limit=limit, offset=offset, q=q, status=status, priority=priority
    )


@router.get("/projects/{project_id}/stories/{story_id}", response_model=Story)
def get_story(story_id: UUID, context: Context, service: Service) -> Story:
    context.require("backlog:read")
    story = service.get(context.project_id, story_id)
    if story is None:
        raise HTTPException(404, "Project unavailable")
    return story


@router.patch("/projects/{project_id}/stories/{story_id}", response_model=Story)
def update_story(story_id: UUID, change: StoryChange, context: Context, service: Service) -> Story:
    context.require(
        "backlog:update_status" if change.model_fields_set == {"status"} else "backlog:update"
    )
    story = service.update(context.project_id, story_id, change)
    if story is None:
        raise HTTPException(404, "Project unavailable")
    return story


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
def ready(request: Request) -> dict[str, str]:
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(select(StoryRecord.id).limit(1))
    except SQLAlchemyError:
        raise HTTPException(503, "Service temporarily unavailable") from None
    return {"status": "ready"}
