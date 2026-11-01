"""HTTP authentication adapters and request-scoped dependency composition."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backlog_service.database import check_readiness
from backlog_service.domain import ProjectContext, ReviewPrincipal
from backlog_service.project_access import (
    ProjectsUnavailable,
    ProjectUnavailable,
    ProjectWriteControl,
)
from backlog_service.project_source import AuthorizedProjectSource
from backlog_service.recommendation_service import RecommendationsService
from backlog_service.repository import StoryRepository
from backlog_service.review_auth import authorize_review_principal
from backlog_service.review_service import ReviewService
from backlog_service.security import AuthenticationRejected, SigningKeysUnavailable
from backlog_service.service import StoriesService

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    actor_id: UUID
    token: str = field(repr=False)


def unauthorized() -> HTTPException:
    return HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})


def current_principal(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Principal:
    if credentials is None:
        raise unauthorized()
    try:
        actor: UUID = request.app.state.verifier.verify(credentials.credentials)
        if request.app.state.settings.auth_session_check_enabled:
            request.app.state.identity_status.check(credentials.credentials, actor)
        return Principal(actor, credentials.credentials)
    except AuthenticationRejected:
        raise unauthorized() from None
    except (SigningKeysUnavailable, ProjectsUnavailable):
        raise HTTPException(503, "Service temporarily unavailable") from None


def authorized_project(
    project_id: UUID, request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> ProjectContext:
    try:
        context: ProjectContext = request.app.state.project_access.context(
            project_id, principal.actor_id, principal.token
        )
    except ProjectUnavailable:
        raise HTTPException(404, "Project unavailable") from None
    except AuthenticationRejected:
        raise unauthorized() from None
    except ProjectsUnavailable:
        raise HTTPException(503, "Service temporarily unavailable") from None
    return context


Context = Annotated[ProjectContext, Depends(authorized_project)]


def story_service(
    request: Request, context: Context, principal: Annotated[Principal, Depends(current_principal)]
) -> Iterator[StoriesService]:
    with Session(request.app.state.engine, expire_on_commit=False) as session:
        yield StoriesService(
            StoryRepository(session),
            control=request.app.state.write_control
            or ProjectWriteControl(request.app.state.project_access, principal.token),
        )


Service = Annotated[StoriesService, Depends(story_service)]


def readiness_check(request: Request) -> None:
    check_readiness(request.app.state.engine)


Readiness = Annotated[None, Depends(readiness_check)]


def recommendations_service(
    request: Request,
    items: Service,
    principal: Annotated[Principal, Depends(current_principal)],
) -> RecommendationsService:
    return RecommendationsService(
        items,
        AuthorizedProjectSource(request.app.state.project_access, principal.token),
        request.app.state.ai_provider,
    )


Recommendations = Annotated[RecommendationsService, Depends(recommendations_service)]


def review_principal(project_id: UUID, request: Request) -> ReviewPrincipal:
    return authorize_review_principal(
        request.app.state.settings, project_id, request.headers.getlist("x-code-review-key")
    )


ReviewGate = Annotated[ReviewPrincipal, Depends(review_principal)]


def review_service(request: Request, gate: ReviewGate, items: Service) -> ReviewService:
    return ReviewService(items, request.app.state.settings.code_review_event_mapping, gate)


ReviewEvents = Annotated[ReviewService, Depends(review_service)]
