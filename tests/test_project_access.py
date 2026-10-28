from uuid import uuid4

import httpx
import pytest

from backlog_service.project_access import ProjectAccess, ProjectsUnavailable, ProjectUnavailable
from backlog_service.security import AuthenticationRejected


def test_each_operation_confirms_project_and_forwards_bearer(project_id, actor_id, access_payload):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=access_payload(project_id, actor_id))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        access = ProjectAccess(client, "http://127.0.0.1:8001")
        for _ in range(2):
            access.require_access(project_id, actor_id, "synthetic-token")
    assert len(requests) == 2
    for request in requests:
        assert str(request.url) == f"http://127.0.0.1:8001/projects/{project_id}/access"
        assert request.headers["Authorization"] == "Bearer synthetic-token"
        assert request.headers["Cache-Control"] == "no-store"
        assert request.extensions["timeout"]["read"] == 5


@pytest.mark.parametrize(
    "case",
    [
        "wrong-id",
        "wrong-owner",
        "invalid",
        "list",
        "json",
        "redirect",
        "timeout",
        "server",
        "forbidden",
    ],
)
def test_inconsistent_or_unavailable_projects_fail_closed(
    project_id, actor_id, case, access_payload
):
    requests = []

    def respond(request):
        requests.append(request)
        if case == "timeout":
            raise httpx.ReadTimeout("private detail", request=request)
        if case == "redirect":
            return httpx.Response(302, headers={"Location": "https://remote.invalid"})
        if case == "server":
            return httpx.Response(503)
        if case == "forbidden":
            return httpx.Response(403)
        if case == "json":
            return httpx.Response(200, content="invalid")
        payload = access_payload(project_id, actor_id)
        if case == "wrong-id":
            payload["project_id"] = str(uuid4())
        if case == "wrong-owner":
            payload["user_id"] = str(uuid4())
        if case == "invalid":
            payload["user_id"] = "invalid"
        return httpx.Response(200, json=[] if case == "list" else payload)

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        with pytest.raises(ProjectsUnavailable) as error:
            ProjectAccess(client, "http://127.0.0.1:8001").require_access(
                project_id, actor_id, "synthetic"
            )
    assert len(requests) == 1
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "status,exception", [(404, ProjectUnavailable), (401, AuthenticationRejected)]
)
def test_projects_rejections(project_id, actor_id, status, exception):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status))) as client:
        with pytest.raises(exception):
            ProjectAccess(client, "http://127.0.0.1:8001").require_access(
                project_id, actor_id, "synthetic"
            )


@pytest.mark.parametrize(
    "patch",
    [
        {"project_id": None},
        {"project_id": 12},
        {"user_id": None},
        {"is_owner": 1},
        {"is_owner": "true"},
        {"is_owner": None},
        {"roles": "owner"},
        {"roles": ["administrator"]},
        {"roles": ["owner", "developer"]},
        {"roles": ["owner", "owner"]},
        {"roles": [1]},
        {"roles": None},
        {"is_owner": False},
        {"permissions": "backlog:read"},
        {"permissions": ["backlog:read", "backlog:read"]},
        {"permissions": ["backlog:delete"]},
        {"permissions": [1]},
        {"permissions": None},
        {"permissions": []},
        {"roles": []},
    ],
)
def test_malformed_access_never_confers_permissions(project_id, actor_id, access_payload, patch):
    payload = access_payload(project_id, actor_id) | patch
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ProjectsUnavailable):
            ProjectAccess(client, "http://127.0.0.1:8001").require_access(
                project_id, actor_id, "synthetic"
            )


@pytest.mark.parametrize("field", ["project_id", "user_id", "is_owner", "roles", "permissions"])
def test_access_fields_are_required(project_id, actor_id, access_payload, field):
    payload = access_payload(project_id, actor_id)
    del payload[field]
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ProjectsUnavailable):
            ProjectAccess(client, "http://127.0.0.1:8001").require_access(
                project_id, actor_id, "synthetic"
            )


def test_legacy_owner_payload_is_not_authorization(project_id, actor_id):
    payload = {"id": str(project_id), "owner_id": str(actor_id)}
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ProjectsUnavailable):
            ProjectAccess(client, "http://127.0.0.1:8001").require_access(
                project_id, actor_id, "synthetic"
            )


@pytest.mark.parametrize(
    "roles,add,remove",
    [
        (["developer"], "backlog:update", None),
        (["product_owner"], "project:delete", None),
        (["project_manager"], "project:delete", None),
        (["developer"], None, "backlog:update_status"),
        (["developer", "product_owner"], None, "backlog:create"),
    ],
)
def test_incoherent_role_permission_union_is_unavailable(
    project_id, actor_id, access_payload, roles, add, remove
):
    payload = access_payload(project_id, actor_id, roles=roles)
    if add:
        payload["permissions"].append(add)
    if remove:
        payload["permissions"].remove(remove)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ProjectsUnavailable):
            ProjectAccess(client, "http://127.0.0.1:8001").require_access(
                project_id, actor_id, "synthetic"
            )
