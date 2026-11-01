from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from test_online_control import payload

from backlog_service.app import create_app
from backlog_service.database import init_schema
from backlog_service.identity_status import IdentityStatusClient
from backlog_service.models import StoryRecord
from backlog_service.project_access import ProjectAccess


@pytest.fixture
def expanded_client(issuer, project_id):
    state = {
        "access": payload(project_id, issuer["owner"]),
        "active": True,
        "leases": [],
        "lease_status": 201,
        "calls": [],
    }
    state["access"]["permissions"].extend(["backlog:update", "backlog:update_status"])
    state["access"]["role_definitions"][0]["permissions"] = state["access"]["permissions"][:]

    def handler(request):
        state["calls"].append(request)
        if request.url.path == "/auth/me":
            return httpx.Response(
                200, json={"id": str(issuer["owner"]), "is_active": state["active"]}
            )
        if request.url.path.endswith("/access/v2"):
            return httpx.Response(200, json=state["access"])
        if request.method == "POST" and request.url.path.endswith("/write-leases"):
            lease = str(uuid4())
            state["leases"].append(lease)
            return httpx.Response(
                state["lease_status"], json={"lease_id": lease, "project_id": str(project_id)}
            )
        if request.method == "DELETE":
            with app.state.engine.connect() as conn:
                state["committed_at_release"] = conn.scalar(
                    select(func.count()).select_from(StoryRecord)
                )
            return httpx.Response(204)
        if request.url.path.endswith("/eligibility"):
            return httpx.Response(
                state.get("eligibility_status", 200),
                json={
                    "user_id": request.url.path.split("/")[-2],
                    "eligible": state.get("eligible", True),
                    "roles": ["developer"],
                    "permissions": ["backlog:read"],
                },
            )
        if request.url.path == f"/projects/{project_id}":
            return httpx.Response(
                200,
                json={
                    "id": str(project_id),
                    "description": "Actual product description",
                    "version": state.get("project_version", 1),
                },
            )
        return httpx.Response(404)

    upstream = httpx.Client(transport=httpx.MockTransport(handler))
    settings = issuer["settings"].model_copy(update={"auth_session_check_enabled": True})
    app = create_app(
        settings,
        project_access=ProjectAccess(upstream, "http://projects"),
        identity_status=IdentityStatusClient(upstream, "http://identity"),
    )
    init_schema(app.state.engine, "backlog")
    with TestClient(app) as client:
        yield client, state, {"Authorization": "Bearer " + issuer["token"]()}
    upstream.close()


def test_http_items_lease_commit_and_contract(expanded_client, project_id):
    client, state, headers = expanded_client
    url = f"/projects/{project_id}"
    result = client.post(
        url + "/items",
        json={
            "title": "Story",
            "estimate_value": "2.5",
            "estimate_unit": "points",
            "assignee_id": str(uuid4()),
        },
        headers=headers,
    )
    assert result.status_code == 201, result.text
    assert state["committed_at_release"] == 1
    item = result.json()
    update = client.patch(
        url + "/items/" + item["id"],
        json={"status": "done", "expected_version": 1},
        headers=headers,
    )
    assert update.status_code == 200 and update.json()["version"] == 2
    assert client.get(url + "/stories", headers=headers).json()["total"] == 1
    assert (
        client.get(url + "/board", headers=headers).json()["columns"]["done"][0]["id"] == item["id"]
    )
    reordered = client.post(
        url + "/items/reorder",
        headers=headers,
        json={"item_ids": [item["id"]], "expected_version": 2},
    )
    assert reordered.status_code == 200, reordered.text
    summary = client.get(url + "/content-summary", headers=headers).json()
    assert summary["history"] == 3 and summary["total"] == 4


def test_online_revocation_and_lifecycle_before_db(expanded_client, project_id):
    client, state, headers = expanded_client
    statements = []
    event.listen(
        client.app.state.engine,
        "before_cursor_execute",
        lambda c, cur, sql, p, ctx, many: statements.append(sql),
    )
    state["active"] = False
    assert client.get(f"/projects/{project_id}/items", headers=headers).status_code == 401
    state["active"] = True
    state["access"]["project_status"] = "suspended"
    assert (
        client.post(
            f"/projects/{project_id}/stories", headers=headers, json={"title": "Denied"}
        ).status_code
        == 409
    )
    assert statements == [] and state["leases"] == []
    assert client.get(f"/projects/{project_id}/content-summary", headers=headers).status_code == 200


def test_failed_lease_prevents_write_and_eligibility_rolls_back(expanded_client, project_id):
    client, state, headers = expanded_client
    state["lease_status"] = 409
    assert (
        client.post(
            f"/projects/{project_id}/items", headers=headers, json={"title": "Denied"}
        ).status_code
        == 409
    )
    state["lease_status"] = 201
    state["eligible"] = False
    result = client.post(
        f"/projects/{project_id}/items",
        headers=headers,
        json={"title": "Denied", "assignee_id": str(uuid4())},
    )
    assert result.status_code == 409
    assert state["committed_at_release"] == 0


def test_http_recommendation_disabled_then_human_approval(expanded_client, project_id):
    from test_recommendations import Provider

    client, state, headers = expanded_client
    url = f"/projects/{project_id}/recommendations"
    assert client.post(url, json={"kind": "initial_backlog"}, headers=headers).status_code == 503
    client.app.state.ai_provider = Provider()
    result = client.post(url, json={"kind": "initial_backlog"}, headers=headers)
    assert result.status_code == 201, result.text
    rec = result.json()
    assert rec["status"] == "pending" and rec["simulated"] is True
    approved = client.post(
        url + "/" + rec["id"] + "/approve", json={"expected_version": 1}, headers=headers
    )
    assert approved.status_code == 200, approved.text
    assert len(approved.json()["applied_item_ids"]) == 1
    assert client.get(url, headers=headers).json()["total"] == 1
    assert state["committed_at_release"] == 1


def test_http_unavailable_assignee_survives_status_change_and_unknown_read(
    expanded_client, project_id
):
    client, state, headers = expanded_client
    assignee = str(uuid4())
    base = f"/projects/{project_id}/items"
    created = client.post(
        base, json={"title": "Keep attribution", "assignee_id": assignee}, headers=headers
    )
    assert created.status_code == 201 and created.json()["assignee_available"] is True
    item = created.json()
    detail = base + "/" + item["id"]
    state["eligible"] = False
    current = client.get(detail, headers=headers).json()
    assert current["assignee_id"] == assignee and current["assignee_available"] is False
    changed = client.patch(detail, json={"status": "done", "expected_version": 1}, headers=headers)
    assert changed.status_code == 200, changed.text
    assert (
        changed.json()["assignee_id"] == assignee and changed.json()["assignee_available"] is False
    )
    state["eligibility_status"] = 503
    assert client.get(detail, headers=headers).json()["assignee_available"] is None
    denied = client.patch(
        detail, json={"assignee_id": str(uuid4()), "expected_version": 2}, headers=headers
    )
    assert denied.status_code == 503
    assert client.get(detail, headers=headers).json()["version"] == 2
