"""Authorized project data source; never calls project summary or foreign SQL."""

from typing import Any
from uuid import UUID

from backlog_service.domain import DependencyUnavailable
from backlog_service.project_access import ProjectAccess


class AuthorizedProjectSource:
    def __init__(self, access: ProjectAccess, token: str) -> None:
        self.access, self.token = access, token

    def get(self, project_id: UUID) -> dict[str, Any]:
        result = self.access.request("GET", f"/projects/{project_id}", self.token)
        if not isinstance(result, dict):
            raise DependencyUnavailable("Service temporarily unavailable")
        return result
