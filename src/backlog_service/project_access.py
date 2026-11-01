from uuid import UUID

import httpx

from backlog_service.domain import ProjectContext
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
    def __init__(self, client: httpx.Client, base_url: str, *, legacy_access: bool = False) -> None:
        self.legacy_access = legacy_access
        self.client = client
        self.base_url = base_url.rstrip("/")

    def context(self, project_id: UUID, actor_id: UUID, token: str) -> ProjectContext:
        from backlog_service.domain import ProjectContext

        if self.legacy_access:
            return ProjectContext(
                project_id, actor_id, self.require_access(project_id, actor_id, token)
            )
        return validated_v2(
            self.request("GET", f"/projects/{project_id}/access/v2", token), project_id, actor_id
        )

    def request(
        self, method: str, path: str, token: str, body: dict[str, object] | None = None
    ) -> object:
        from backlog_service.domain import Conflict, InsufficientProjectPermissions

        try:
            response = self.client.request(
                method,
                self.base_url + path,
                json=body,
                headers={"Authorization": f"Bearer {token}", "Cache-Control": "no-store"},
                timeout=5,
                follow_redirects=False,
            )
            if response.status_code == 401:
                raise AuthenticationRejected("Authentication required")
            if response.status_code == 403:
                raise InsufficientProjectPermissions("Insufficient project permissions")
            if response.status_code == 404:
                raise ProjectUnavailable("Project unavailable")
            if response.status_code == 409:
                raise Conflict("Project write conflict")
            if response.status_code not in {200, 201, 204}:
                raise ProjectsUnavailable("Service temporarily unavailable")
            return None if response.status_code == 204 else response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            raise ProjectsUnavailable("Service temporarily unavailable") from None

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


V2_PERMISSIONS = PERMISSIONS | {
    "project:lifecycle:manage",
    "project:audit:read",
    "project:roles:manage",
    "project:teams:manage",
    "backlog:reorder",
}


V2_ROLE_PERMISSIONS = {
    "developer": DEVELOPER,
    "product_owner": PRODUCT_OWNER,
    "project_manager": PRODUCT_OWNER
    | {
        "project:members:manage",
        "project:lifecycle:manage",
        "project:audit:read",
        "project:roles:manage",
        "project:teams:manage",
        "backlog:reorder",
    },
    "owner": V2_PERMISSIONS,
}


def validated_v2(payload: object, project_id: UUID, actor_id: UUID) -> ProjectContext:
    from backlog_service.domain import ProjectContext

    try:
        if (
            not isinstance(payload, dict)
            or payload.get("access_version") != 2
            or type(payload.get("access_version")) is not int
        ):
            raise ValueError
        if not isinstance(payload["project_id"], str) or not isinstance(payload["user_id"], str):
            raise ValueError
        if UUID(payload["project_id"]) != project_id or UUID(payload["user_id"]) != actor_id:
            raise ValueError
        if (
            type(payload["is_owner"]) is not bool
            or type(payload["archived"]) is not bool
            or type(payload["version"]) is not int
            or payload["version"] < 1
        ):
            raise ValueError
        if (
            payload["project_status"] not in {"planned", "active", "suspended", "completed"}
            or (payload["archived"] and payload["project_status"] != "completed")
            or not isinstance(payload["origins"], list)
        ):
            raise ValueError
        definitions = payload["role_definitions"]
        if not isinstance(definitions, list) or not definitions or len(definitions) > 200:
            raise ValueError
        catalog: dict[str, frozenset[str]] = {}
        for definition in definitions:
            if not isinstance(definition, dict) or set(definition) != {
                "key",
                "name",
                "permissions",
            }:
                raise ValueError
            key, permissions = definition["key"], definition["permissions"]
            if (
                not isinstance(key, str)
                or key in catalog
                or not isinstance(definition["name"], str)
                or not definition["name"].strip()
            ):
                raise ValueError
            if key not in ROLES:
                if not key.startswith("custom:"):
                    raise ValueError
                UUID(key[7:])
            if (
                not isinstance(permissions, list)
                or any(not isinstance(p, str) or p not in V2_PERMISSIONS for p in permissions)
                or len(set(permissions)) != len(permissions)
            ):
                raise ValueError
            if key != "owner" and "project:delete" in permissions:
                raise ValueError
            if key in V2_ROLE_PERMISSIONS and frozenset(permissions) != V2_ROLE_PERMISSIONS[key]:
                raise ValueError
            if key.startswith("custom:") and "project:read" not in permissions:
                raise ValueError
            catalog[key] = frozenset(permissions)
        roles, permissions = payload["roles"], payload["permissions"]
        if (
            not isinstance(roles, list)
            or not roles
            or any(not isinstance(r, str) or r not in catalog for r in roles)
            or len(set(roles)) != len(roles)
        ):
            raise ValueError
        if (roles == ["owner"]) != payload["is_owner"] or ("owner" in roles and roles != ["owner"]):
            raise ValueError
        if (
            not isinstance(permissions, list)
            or any(not isinstance(p, str) or p not in V2_PERMISSIONS for p in permissions)
            or len(set(permissions)) != len(permissions)
            or "project:read" not in permissions
        ):
            raise ValueError
        if frozenset(permissions) != frozenset().union(*(catalog[r] for r in roles)):
            raise ValueError
        for origin in payload["origins"]:
            if not isinstance(origin, dict) or origin.get("type") not in {
                "owner",
                "direct",
                "team",
            }:
                raise ValueError
            origin_roles = origin.get("roles")
            if (
                not isinstance(origin_roles, list)
                or not origin_roles
                or any(not isinstance(role, str) or role not in roles for role in origin_roles)
                or len(set(origin_roles)) != len(origin_roles)
            ):
                raise ValueError
            if origin["type"] == "owner" and (not payload["is_owner"] or origin_roles != ["owner"]):
                raise ValueError
            if origin["type"] != "owner" and "owner" in origin_roles:
                raise ValueError
            if origin["type"] == "team":
                if not isinstance(origin.get("team_id"), str):
                    raise ValueError
                UUID(origin["team_id"])
        return ProjectContext(
            project_id,
            actor_id,
            frozenset(permissions),
            payload["project_status"],
            payload["archived"],
        )
    except (KeyError, ValueError, TypeError):
        raise ProjectsUnavailable("Service temporarily unavailable") from None


class ProjectWriteControl:
    def __init__(self, access: ProjectAccess, token: str) -> None:
        self.access, self.token = access, token

    def acquire(self, project_id: UUID) -> UUID:
        from uuid import uuid4

        payload = self.access.request(
            "POST",
            f"/projects/{project_id}/write-leases",
            self.token,
            {"operation_id": str(uuid4())},
        )
        try:
            if not isinstance(payload, dict) or UUID(payload["project_id"]) != project_id:
                raise ValueError
            return UUID(payload["lease_id"])
        except (KeyError, TypeError, ValueError):
            raise ProjectsUnavailable("Service temporarily unavailable") from None

    def release(self, project_id: UUID, lease_id: UUID) -> None:
        self.access.request("DELETE", f"/projects/{project_id}/write-leases/{lease_id}", self.token)

    def eligible(self, project_id: UUID, user_id: UUID) -> bool:
        payload = self.access.request(
            "GET", f"/projects/{project_id}/members/{user_id}/eligibility", self.token
        )
        try:
            if (
                not isinstance(payload, dict)
                or UUID(payload["user_id"]) != user_id
                or type(payload["eligible"]) is not bool
                or not isinstance(payload["roles"], list)
                or not isinstance(payload["permissions"], list)
            ):
                raise ValueError
            return bool(payload["eligible"])
        except (ValueError, KeyError, TypeError):
            raise ProjectsUnavailable("Service temporarily unavailable") from None

    def availability(self, project_id: UUID, user_id: UUID) -> bool | None:
        from backlog_service.domain import InsufficientProjectPermissions

        try:
            return self.eligible(project_id, user_id)
        except ProjectUnavailable:
            return False
        except (ProjectsUnavailable, InsufficientProjectPermissions):
            return None
