from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import event as sql_event
from test_expanded_api import expanded_client as expanded_client

SYNTHETIC_REVIEW_KEY = "controlled-local-review-key-32-characters"


def configure(client, project_id, **changes):
    values = {
        "code_review_enabled": True,
        "code_review_key": SecretStr(SYNTHETIC_REVIEW_KEY),
        "code_review_project_ids": [project_id],
        "code_review_event_mapping": {"locally_agreed_merge": "done"},
    }
    client.app.state.settings = client.app.state.settings.model_copy(update=values | changes)


def draft(project_id, item_id):
    return {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "project_id": str(project_id),
        "item_id": item_id,
        "event_type": "locally_agreed_merge",
        "occurred_at": datetime.now(UTC).isoformat(),
        "expected_item_version": 1,
    }


def test_review_http_disabled_default_and_double_auth_before_item_sql(expanded_client, project_id):
    client, state, headers = expanded_client
    body = draft(project_id, str(uuid4()))
    url = f"/projects/{project_id}/code-review/events"
    statements = []
    sql_event.listen(
        client.app.state.engine,
        "before_cursor_execute",
        lambda c, cur, sql, p, ec, many: statements.append(sql),
    )
    assert client.post(url, json=body, headers=headers).status_code == 503
    configure(client, project_id)
    assert client.post(url, json=body, headers=headers).status_code == 401
    assert (
        client.post(url, json=body, headers=headers | {"X-Code-Review-Key": "wrong"}).status_code
        == 401
    )
    valid = headers | {"X-Code-Review-Key": SYNTHETIC_REVIEW_KEY}
    assert (
        client.post(url, json=body, headers={"X-Code-Review-Key": SYNTHETIC_REVIEW_KEY}).status_code
        == 401
    )
    configure(client, uuid4())
    assert client.post(url, json=body, headers=valid).status_code == 403
    configure(client, project_id, code_review_event_mapping={})
    assert client.post(url, json=body, headers=valid).status_code == 503
    assert statements == []
    assert all("write-leases" not in request.url.path for request in state["calls"])


def test_review_http_current_permission_and_lease_then_idempotent(expanded_client, project_id):
    client, state, headers = expanded_client
    item = client.post(
        f"/projects/{project_id}/items", json={"title": "Preserve text"}, headers=headers
    ).json()
    configure(client, project_id)
    valid = headers | {"X-Code-Review-Key": SYNTHETIC_REVIEW_KEY}
    body = draft(project_id, item["id"])
    url = f"/projects/{project_id}/code-review/events"
    state["lease_status"] = 409
    assert client.post(url, json=body, headers=valid).status_code == 409
    state["lease_status"] = 201
    response = client.post(url, json=body, headers=valid)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done" and response.json()["item_version"] == 2
    assert client.post(url, json=body, headers=valid).json() == response.json()
    assert (
        client.post(url, json=body | {"expected_item_version": 2}, headers=valid).status_code == 409
    )
    current = client.get(f"/projects/{project_id}/items/{item['id']}", headers=headers).json()
    assert current["title"] == "Preserve text" and current["version"] == 2
    state["access"]["permissions"].remove("backlog:update_status")
    state["access"]["role_definitions"][0]["permissions"] = state["access"]["permissions"][:]
    assert client.post(url, json=draft(project_id, item["id"]), headers=valid).status_code == 403


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"occurred_at": "2026-10-11T00:00:00"},
        {"expected_item_version": True},
        {"event_type": "x" * 81},
        {"admin_override": True},
        {"item_id": "not-uuid"},
    ],
)
def test_review_http_strict_envelope(expanded_client, project_id, change):
    client, state, headers = expanded_client
    configure(client, project_id)
    response = client.post(
        f"/projects/{project_id}/code-review/events",
        json=draft(project_id, str(uuid4())) | change,
        headers=headers | {"X-Code-Review-Key": SYNTHETIC_REVIEW_KEY},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid story input"}
