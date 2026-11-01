from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError

from backlog_service.ai_provider import HTTPProposalProvider
from backlog_service.config import Settings
from backlog_service.database import create_database_engine
from backlog_service.domain import (
    Conflict,
    DependencyUnavailable,
    InsufficientProjectPermissions,
    MissingItem,
)
from backlog_service.identity_status import IdentityStatusClient
from backlog_service.item_routes import router as item_router
from backlog_service.item_service import WriteControl
from backlog_service.project_access import ProjectAccess, ProjectsUnavailable, ProjectUnavailable
from backlog_service.recommendation_routes import router as recommendation_router
from backlog_service.recommendation_service import ProposalProvider
from backlog_service.review_routes import router as review_router
from backlog_service.routes import router
from backlog_service.security import AuthenticationRejected, TokenVerifier


def create_app(
    settings: Settings | None = None,
    *,
    verifier: TokenVerifier | None = None,
    project_access: ProjectAccess | None = None,
    identity_status: IdentityStatusClient | None = None,
    write_control: WriteControl | None = None,
    ai_provider: ProposalProvider | None = None,
) -> FastAPI:
    settings = settings or Settings()
    engine = create_database_engine(settings)
    client = httpx.Client(timeout=5, follow_redirects=False, trust_env=False)
    if project_access is None:
        project_access = ProjectAccess(
            client,
            settings.projects_api_base_url,
            legacy_access=settings.projects_legacy_access_enabled,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()
            if client is not None:
                client.close()

    app = FastAPI(title="Módulo 1 — Backlog", version=version("backlog-service"), lifespan=lifespan)
    app.state.ai_provider = ai_provider or HTTPProposalProvider(client, settings)
    app.state.settings = settings
    app.state.identity_status = identity_status or IdentityStatusClient(
        client, settings.auth_api_base_url
    )
    app.state.write_control = write_control
    app.state.engine = engine
    app.state.verifier = verifier or TokenVerifier(settings)
    app.state.project_access = project_access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def no_store(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/projects/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "Invalid story input"})

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(request: Request, error: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})

    @app.exception_handler(InsufficientProjectPermissions)
    async def insufficient_permissions(
        request: Request, error: InsufficientProjectPermissions
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": "Insufficient project permissions"})

    @app.exception_handler(Conflict)
    async def conflict(request: Request, error: Conflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(MissingItem)
    @app.exception_handler(ProjectUnavailable)
    async def missing(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Project unavailable"})

    @app.exception_handler(ProjectsUnavailable)
    @app.exception_handler(DependencyUnavailable)
    async def upstream_unavailable(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})

    @app.exception_handler(AuthenticationRejected)
    async def rejected(request: Request, error: AuthenticationRejected) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    app.include_router(review_router)
    app.include_router(recommendation_router)
    app.include_router(item_router)
    app.include_router(router)
    return app
