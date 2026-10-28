from uuid import UUID

import httpx

from backlog_service.security import AuthenticationRejected

PERMISSIONS = frozenset(
    {
        "project:read",
        "project:update",
        "project:delete",
        "project:members:read",
        "project:members:manage",
        "backlog:read",
        "backlog:create",
        "backlog:update",
        "backlog:update_status",
    }
)
ROLES = frozenset({"owner", "product_owner", "project_manager", "developer"})
DEVELOPER = frozenset(
    {"project:read", "project:members:read", "backlog:read", "backlog:update_status"}
)
PRODUCT_OWNER = DEVELOPER | {"project:update", "backlog:create", "backlog:update"}
ROLE_PERMISSIONS = {
    "owner": PERMISSIONS,
    "developer": DEVELOPER,
    "product_owner": PRODUCT_OWNER,
    "project_manager": PRODUCT_OWNER | {"project:members:manage"},
}


def validated_permissions(payload: object, project_id: UUID, actor_id: UUID) -> frozenset[str]:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"project_id", "user_id", "is_owner", "roles", "permissions"}
        or not isinstance(payload["project_id"], str)
        or not isinstance(payload["user_id"], str)
        or UUID(payload["project_id"]) != project_id
        or UUID(payload["user_id"]) != actor_id
        or not isinstance(payload["is_owner"], bool)
    ):
        raise ProjectsUnavailable("Service temporarily unavailable")
    roles = payload["roles"]
    permissions = payload["permissions"]
    if (
        not isinstance(roles, list)
        or not roles
        or any(not isinstance(role, str) or role not in ROLES for role in roles)
        or len(set(roles)) != len(roles)
        or (roles == ["owner"]) != payload["is_owner"]
        or ("owner" in roles and roles != ["owner"])
        or not isinstance(permissions, list)
        or any(not isinstance(p, str) or p not in PERMISSIONS for p in permissions)
        or len(set(permissions)) != len(permissions)
        or "project:read" not in permissions
        or (payload["is_owner"] and set(permissions) != PERMISSIONS)
    ):
        raise ProjectsUnavailable("Service temporarily unavailable")
    expected = frozenset().union(*(ROLE_PERMISSIONS[role] for role in roles))
    if set(permissions) != expected:
        raise ProjectsUnavailable("Service temporarily unavailable")
    return frozenset(permissions)


class ProjectUnavailable(Exception):
    pass


class ProjectsUnavailable(Exception):
    pass


class ProjectAccess:
    def __init__(self, client: httpx.Client, base_url: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")

    def require_access(self, project_id: UUID, actor_id: UUID, token: str) -> frozenset[str]:
        try:
            response = self.client.get(
                f"{self.base_url}/projects/{project_id}/access",
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
            return validated_permissions(response.json(), project_id, actor_id)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise ProjectsUnavailable("Service temporarily unavailable") from None
