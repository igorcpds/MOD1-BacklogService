from uuid import uuid4

import httpx
import pytest

from backlog_service.identity_status import IdentityStatusClient
from backlog_service.project_access import ProjectAccess, ProjectsUnavailable, validated_v2
from backlog_service.security import AuthenticationRejected


def payload(project, actor):
    permissions = ["project:read", "backlog:read", "backlog:create", "backlog:reorder"]
    return {
        "access_version": 2,
        "project_id": str(project),
        "user_id": str(actor),
        "is_owner": False,
        "roles": ["custom:" + str(project)],
        "permissions": permissions,
        "role_definitions": [
            {"key": "custom:" + str(project), "name": "Planner", "permissions": permissions}
        ],
        "project_status": "active",
        "archived": False,
        "version": 1,
        "origins": [],
    }


def test_online_identity_rejects_revocation_and_mismatch(actor_id):
    state = {"id": str(actor_id), "is_active": True}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=state)))
    check = IdentityStatusClient(client, "http://identity")
    check.check("bearer", actor_id)
    state["is_active"] = False
    with pytest.raises(AuthenticationRejected):
        check.check("bearer", actor_id)
    state.update(id=str(uuid4()), is_active=True)
    with pytest.raises(ProjectsUnavailable):
        check.check("bearer", actor_id)


def test_v2_catalog_and_coherence(project_id, actor_id):
    data = payload(project_id, actor_id)
    assert "backlog:reorder" in validated_v2(data, project_id, actor_id).permissions
    data["permissions"].append("unknown:admin")
    with pytest.raises(ProjectsUnavailable):
        validated_v2(data, project_id, actor_id)


def test_v2_never_falls_back_on_denial_or_invalid(project_id, actor_id):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"access_version": 2})

    access = ProjectAccess(httpx.Client(transport=httpx.MockTransport(handler)), "http://projects")
    with pytest.raises(ProjectsUnavailable):
        access.context(project_id, actor_id, "token")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", None),
        ("project_id", []),
        ("user_id", 123),
        ("origins", [{"type": "team", "team_id": "invalid", "roles": ["developer"]}]),
    ],
)
def test_v2_malformed_identifiers_and_origins_are_dependency_failures(
    project_id, actor_id, field, value
):
    data = payload(project_id, actor_id)
    data[field] = value
    with pytest.raises(ProjectsUnavailable):
        validated_v2(data, project_id, actor_id)
