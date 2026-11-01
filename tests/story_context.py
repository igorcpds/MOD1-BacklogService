"""Explicitly authorized contexts for synthetic service/persistence fixtures."""

from uuid import UUID

from backlog_service.domain import ProjectContext


def context_for(project_id, actor_id=UUID("22222222-2222-4222-8222-222222222222")):
    return ProjectContext(
        project_id,
        actor_id,
        frozenset({"backlog:read", "backlog:create", "backlog:update", "backlog:update_status"}),
    )
