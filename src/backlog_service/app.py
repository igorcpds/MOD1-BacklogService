from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError

from backlog_service.config import Settings
from backlog_service.database import create_database_engine
from backlog_service.project_access import ProjectAccess
from backlog_service.routes import router
from backlog_service.security import TokenVerifier


def create_app(
    settings: Settings | None = None,
    *,
    verifier: TokenVerifier | None = None,
    project_access: ProjectAccess | None = None,
) -> FastAPI:
    settings = settings or Settings()
    engine = create_database_engine(settings)
    client: httpx.Client | None = None
    if project_access is None:
        client = httpx.Client(timeout=5, follow_redirects=False, trust_env=False)
        project_access = ProjectAccess(client, settings.projects_api_base_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()
            if client is not None:
                client.close()

    app = FastAPI(title="Módulo 1 — Backlog", version="0.2.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.verifier = verifier or TokenVerifier(settings)
    app.state.project_access = project_access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH"],
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

    app.include_router(router)
    return app
