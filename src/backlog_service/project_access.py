from uuid import UUID

import httpx

from backlog_service.security import AuthenticationRejected


class ProjectUnavailable(Exception):
    pass


class ProjectsUnavailable(Exception):
    pass


class ProjectAccess:
    def __init__(self, client: httpx.Client, base_url: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")

    def require_access(self, project_id: UUID, actor_id: UUID, token: str) -> None:
        try:
            response = self.client.get(
                f"{self.base_url}/projects/{project_id}",
                headers={"Authorization": f"Bearer {token}", "Cache-Control": "no-store"},
                timeout=5,
                follow_redirects=False,
            )
            if response.status_code == 404:
                raise ProjectUnavailable("Project unavailable")
            if response.status_code == 401:
                raise AuthenticationRejected("Authentication required")
            if response.status_code != 200:
                raise ProjectsUnavailable("Service temporarily unavailable")
            payload = response.json()
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("id"), str)
                or not isinstance(payload.get("owner_id"), str)
                or UUID(payload["id"]) != project_id
                or UUID(payload["owner_id"]) != actor_id
            ):
                raise ProjectsUnavailable("Service temporarily unavailable")
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise ProjectsUnavailable("Service temporarily unavailable") from None
