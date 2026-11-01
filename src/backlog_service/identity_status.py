"""Authoritative Identity state check, with no positive cache."""

from uuid import UUID

import httpx

from backlog_service.project_access import ProjectsUnavailable
from backlog_service.security import AuthenticationRejected


class IdentityStatusClient:
    def __init__(self, client: httpx.Client, base_url: str) -> None:
        self.client, self.base_url = client, base_url.rstrip("/")

    def check(self, token: str, user_id: UUID) -> None:
        try:
            response = self.client.get(
                self.base_url + "/auth/me",
                headers={"Authorization": f"Bearer {token}", "Cache-Control": "no-store"},
                timeout=5,
                follow_redirects=False,
            )
            if response.status_code == 401:
                raise AuthenticationRejected("Authentication required")
            if response.status_code != 200:
                raise ProjectsUnavailable("Service temporarily unavailable")
            payload = response.json()
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("id"), str)
                or UUID(payload["id"]) != user_id
                or not isinstance(payload.get("is_active"), bool)
            ):
                raise ProjectsUnavailable("Service temporarily unavailable")
            if not payload["is_active"]:
                raise AuthenticationRejected("Authentication required")
        except (httpx.HTTPError, ValueError, TypeError):
            raise ProjectsUnavailable("Service temporarily unavailable") from None
