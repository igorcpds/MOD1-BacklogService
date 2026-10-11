from uuid import uuid4

import httpx
import pytest

from backlog_service.project_access import ProjectAccess, ProjectsUnavailable, ProjectUnavailable
from backlog_service.security import AuthenticationRejected


def test_each_operation_confirms_project_and_forwards_bearer(project_id, actor_id):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"id": str(project_id), "owner_id": str(actor_id)})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        access = ProjectAccess(client, "http://127.0.0.1:8001")
        for _ in range(2):
            access.require_access(project_id, actor_id, "synthetic-token")
    assert len(requests) == 2
    for request in requests:
        assert str(request.url) == f"http://127.0.0.1:8001/projects/{project_id}"
        assert request.headers["Authorization"] == "Bearer synthetic-token"
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
def test_inconsistent_or_unavailable_projects_fail_closed(project_id, actor_id, case):
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
        payload = {"id": str(project_id), "owner_id": str(actor_id)}
        if case == "wrong-id":
            payload["id"] = str(uuid4())
        if case == "wrong-owner":
            payload["owner_id"] = str(uuid4())
        if case == "invalid":
            payload["owner_id"] = "invalid"
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
