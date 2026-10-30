from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from backlog_service.app import create_app
from backlog_service.database import init_schema
from backlog_service.project_access import ProjectAccess
from backlog_service.security import SigningKeysUnavailable


@pytest.fixture
def client(issuer, project_id, access_payload):
    state = {"status": 200, "calls": []}

    def projects(request):
        state["calls"].append(request)
        return httpx.Response(
            state["status"],
            json=state.get(
                "payload", access_payload(request.url.path.split("/")[-2], issuer["owner"])
            ),
        )

    upstream = httpx.Client(transport=httpx.MockTransport(projects))
    app = create_app(
        issuer["settings"], project_access=ProjectAccess(upstream, "http://127.0.0.1:8001")
    )
    app.state.test_projects = state
    init_schema(app.state.engine, "backlog")
    with TestClient(app) as client:
        yield client
    upstream.close()


def headers(issuer):
    return {"Authorization": "Bearer " + issuer["token"]()}


def test_story_flow(client, issuer, project_id):
    url = f"/projects/{project_id}/stories"
    auth = headers(issuer)
    response = client.post(url, json={"title": "  História  "}, headers=auth)
    assert response.status_code == 201
    story = response.json()
    assert story["created_by"] == str(issuer["owner"])
    assert story["project_id"] == str(project_id)
    assert (story["title"], story["priority"], story["status"]) == ("História", "medium", "todo")
    detail = f"{url}/{story['id']}"
    assert client.get(detail, headers=auth).json() == story
    assert client.get(url, headers=auth).json() == {
        "items": [story],
        "total": 1,
        "limit": 20,
        "offset": 0,
    }
    same = client.patch(detail, json={"status": "todo"}, headers=auth).json()
    assert same["updated_at"] == story["updated_at"]
    changed = client.patch(detail, json={"priority": "high", "status": "done"}, headers=auth).json()
    assert (changed["priority"], changed["status"]) == ("high", "done")
    assert changed["updated_at"] >= story["updated_at"]
    assert len(client.app.state.test_projects["calls"]) == 5
    assert all(
        r.headers["authorization"] == auth["Authorization"]
        for r in client.app.state.test_projects["calls"]
    )


def test_text_edit_and_filtered_list_reauthorize_each_request(client, issuer, project_id):
    url = f"/projects/{project_id}/stories"
    auth = headers(issuer)
    story = client.post(url, json={"title": "Inicial"}, headers=auth).json()
    changed = client.patch(
        f"{url}/{story['id']}",
        headers=auth,
        json={"title": " Nova história ", "description": "100% ÁRVORE", "status": "done"},
    )
    assert changed.status_code == 200
    assert changed.json()["title"] == "Nova história"
    for query, total in [
        ({"q": " árvore ", "status": "done", "priority": "medium"}, 1),
        ({"q": story["id"].upper()}, 1),
        ({"q": "100_"}, 0),
        ({"q": " " + "x" * 200 + " "}, 0),
        ({"q": "\ufeff"}, 1),
        ({"status": "todo"}, 0),
        ({"priority": "high"}, 0),
    ]:
        response = client.get(url, params=query, headers=auth)
        assert response.status_code == 200
        assert response.json()["total"] == total
    calls = client.app.state.test_projects["calls"]
    assert len(calls) == 9
    assert all(request.method == "GET" for request in calls)
    assert all(request.headers["authorization"] == auth["Authorization"] for request in calls)
    assert all(request.url.path == f"/projects/{project_id}/access" for request in calls)


@pytest.mark.parametrize("query", [{"q": "x" * 201}, {"status": "closed"}, {"priority": "urgent"}])
def test_invalid_search_is_sanitized(client, issuer, project_id, query):
    response = client.get(f"/projects/{project_id}/stories", params=query, headers=headers(issuer))
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid story input"}


@pytest.mark.parametrize("field", ["id", "project_id", "created_by", "created_at", "updated_at"])
def test_patch_immutable_fields_rejected_with_text(client, issuer, project_id, field):
    response = client.patch(
        f"/projects/{project_id}/stories/{uuid4()}",
        json={"title": "Allowed", field: "private"},
        headers=headers(issuer),
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid story input"}


@pytest.mark.parametrize("status,expected", [(404, 404), (401, 401), (503, 503), (302, 503)])
def test_denied_project_never_reads_or_writes_database(
    client, issuer, project_id, status, expected
):
    client.app.state.test_projects["status"] = status
    statements = []
    event.listen(
        client.app.state.engine,
        "before_cursor_execute",
        lambda c, cur, sql, p, ctx, many: statements.append(sql),
    )
    url = f"/projects/{project_id}/stories"
    for method, route, data in [
        ("GET", url, None),
        ("GET", url + "?q=literal%25&status=done&priority=high", None),
        ("POST", url, {"title": "A"}),
        ("GET", f"{url}/{uuid4()}", None),
        ("PATCH", f"{url}/{uuid4()}", {"status": "done"}),
        ("PATCH", f"{url}/{uuid4()}", {"title": "Texto", "description": ""}),
    ]:
        response = client.request(method, route, headers=headers(issuer), json=data)
        assert response.status_code == expected
        assert response.headers["cache-control"] == "no-store"
    assert statements == []


def test_missing_wrong_project_and_story_are_indistinguishable(client, issuer, project_id):
    auth = headers(issuer)
    url = f"/projects/{project_id}/stories"
    story = client.post(url, json={"title": "A"}, headers=auth).json()
    missing = client.get(f"{url}/{uuid4()}", headers=auth)
    other = client.get(f"/projects/{uuid4()}/stories/{story['id']}", headers=auth)
    client.app.state.test_projects["status"] = 404
    denied = client.get(url, headers=auth)
    assert missing.status_code == other.status_code == denied.status_code == 404
    assert missing.json() == other.json() == denied.json()


@pytest.mark.parametrize(
    "method,suffix,data",
    [
        ("POST", "", {"title": {"secret": "input"}}),
        ("POST", "", {"title": "A", "created_by": "private"}),
        ("PATCH", "/11111111-1111-4111-8111-111111111111", {}),
        ("PATCH", "/11111111-1111-4111-8111-111111111111", {"status": None}),
        ("GET", "?limit=0", None),
        ("GET", "?offset=-1", None),
        ("GET", "?limit=101", None),
    ],
)
def test_sanitized_input_errors(client, issuer, project_id, method, suffix, data):
    response = client.request(
        method, f"/projects/{project_id}/stories{suffix}", headers=headers(issuer), json=data
    )
    assert response.status_code == 422
    assert "private" not in response.text and "secret" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_authentication_and_cors(client, project_id):
    url = f"/projects/{project_id}/stories"
    for auth in ({}, {"Authorization": "Bearer private-token"}):
        response = client.get(url, headers=auth)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert "private-token" not in response.text
    assert client.app.state.test_projects["calls"] == []
    response = client.options(
        url,
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    response = client.options(
        url, headers={"Origin": "https://other.invalid", "Access-Control-Request-Method": "PATCH"}
    )
    assert "access-control-allow-origin" not in response.headers


def test_startup_without_ddl_and_explicit_init(issuer):
    app = create_app(issuer["settings"])
    statements = []
    event.listen(
        app.state.engine,
        "before_cursor_execute",
        lambda c, cur, sql, p, ctx, many: statements.append(sql),
    )
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert statements == []
        assert client.get("/health/ready").status_code == 503
        init_schema(app.state.engine, "backlog")
        assert client.get("/health/ready").status_code == 200


def test_database_and_jwks_failure_recovery(client, issuer, project_id, monkeypatch):
    def broken(c, cur, sql, p, ctx, many):
        raise OperationalError(sql, p, Exception("private DSN"))

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", broken)
    url = f"/projects/{project_id}/stories"
    try:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        response = client.post(url, json={"title": "A"}, headers=headers(issuer))
        assert response.status_code == 503 and "private" not in response.text
    finally:
        event.remove(engine, "before_cursor_execute", broken)
    assert client.post(url, json={"title": "A"}, headers=headers(issuer)).status_code == 201

    def unavailable(token):
        raise SigningKeysUnavailable()

    monkeypatch.setattr(client.app.state.verifier, "verify", unavailable)
    assert client.get(url, headers=headers(issuer)).status_code == 503
    assert client.get("/health/live").status_code == 200


@pytest.mark.parametrize(
    "roles,post_status,text_status",
    [
        (["owner"], 201, 200),
        (["developer"], 403, 403),
        (["product_owner"], 201, 200),
        (["project_manager"], 201, 200),
        (["developer", "product_owner"], 201, 200),
        (["developer", "project_manager"], 201, 200),
        (["developer", "product_owner", "project_manager"], 201, 200),
    ],
)
def test_role_permissions_control_each_operation(
    client, issuer, project_id, access_payload, roles, post_status, text_status
):
    auth = headers(issuer)
    url = f"/projects/{project_id}/stories"
    story = client.post(url, json={"title": "Original"}, headers=auth).json()
    detail = f"{url}/{story['id']}"
    client.app.state.test_projects["payload"] = access_payload(
        project_id, issuer["owner"], roles=roles
    )
    assert client.get(url, headers=auth).status_code == 200
    assert client.get(detail, headers=auth).status_code == 200
    assert client.post(url, json={"title": "New"}, headers=auth).status_code == post_status
    status = client.patch(detail, json={"status": "done"}, headers=auth)
    assert status.status_code == 200
    assert status.json()["status"] == "done"
    for change in [
        {"title": "Changed"},
        {"description": "Changed"},
        {"acceptance_criteria": "Changed"},
        {"priority": "high"},
        {"status": "todo", "title": "Changed"},
        {"status": "done", "description": ""},
    ]:
        response = client.patch(detail, json=change, headers=auth)
        assert response.status_code == text_status
        if text_status == 403:
            assert response.json() == {"detail": "Insufficient project permissions"}
            assert "www-authenticate" not in response.headers


@pytest.mark.parametrize(
    "method,suffix,data",
    [
        ("POST", "", {"title": "Denied"}),
        ("PATCH", "/11111111-1111-4111-8111-111111111111", {"title": "Denied"}),
        ("PATCH", "/11111111-1111-4111-8111-111111111111", {"priority": "high"}),
        (
            "PATCH",
            "/11111111-1111-4111-8111-111111111111",
            {"status": "done", "acceptance_criteria": "Denied"},
        ),
    ],
)
def test_forbidden_action_never_executes_sql(
    client, issuer, project_id, access_payload, method, suffix, data
):
    client.app.state.test_projects["payload"] = access_payload(
        project_id, issuer["owner"], roles=["developer"]
    )
    statements = []
    event.listen(
        client.app.state.engine,
        "before_cursor_execute",
        lambda c, cur, sql, p, ctx, many: statements.append(sql),
    )
    response = client.request(
        method,
        f"/projects/{project_id}/stories{suffix}",
        json=data,
        headers={**headers(issuer), "Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient project permissions"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "www-authenticate" not in response.headers
    assert statements == []


@pytest.mark.parametrize("reason", ["revoked", "expired"])
def test_fresh_lookup_revokes_every_next_operation(client, issuer, project_id, reason):
    # Projects owns expiry and membership state, returning the same 404 for either cause.
    state = client.app.state.test_projects
    auth = headers(issuer)
    url = f"/projects/{project_id}/stories"
    story = client.post(url, json={"title": reason}, headers=auth).json()
    assert client.get(url, headers=auth).status_code == 200
    state["status"] = 404
    statements = []
    event.listen(
        client.app.state.engine,
        "before_cursor_execute",
        lambda c, cur, sql, p, ctx, many: statements.append(sql),
    )
    for method, route, data in [
        ("GET", url, None),
        ("GET", f"{url}/{story['id']}", None),
        ("POST", url, {"title": "Denied"}),
        ("PATCH", f"{url}/{story['id']}", {"status": "done"}),
        ("PATCH", f"{url}/{story['id']}", {"title": "Denied"}),
    ]:
        response = client.request(method, route, headers=auth, json=data)
        assert response.status_code == 404
        assert response.json() == {"detail": "Project unavailable"}
    assert len(state["calls"]) == 7
    assert all(r.headers["authorization"] == auth["Authorization"] for r in state["calls"])
    assert statements == []


def test_role_downgrade_is_effective_on_next_write(client, issuer, project_id, access_payload):
    auth = headers(issuer)
    url = f"/projects/{project_id}/stories"
    story = client.post(url, json={"title": "Original"}, headers=auth).json()
    state = client.app.state.test_projects
    state["payload"] = access_payload(project_id, issuer["owner"], roles=["developer"])
    assert client.post(url, json={"title": "Denied"}, headers=auth).status_code == 403
    assert (
        client.patch(f"{url}/{story['id']}", json={"title": "Denied"}, headers=auth).status_code
        == 403
    )
    response = client.patch(f"{url}/{story['id']}", json={"status": "done"}, headers=auth)
    assert response.status_code == 200
    assert response.json()["title"] == "Original"
    assert response.json()["status"] == "done"
