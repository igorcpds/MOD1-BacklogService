from uuid import uuid4

import pytest

# Imported shared pytest fixture.
# ruff: noqa: F811
from test_expanded_api import expanded_client  # noqa: F401
from test_module4_service import Provider


@pytest.mark.parametrize("enabled", [False, True])
def test_review_api_contract_and_disabled_reader_history(expanded_client, project_id, enabled):
    client, state, headers = expanded_client
    client.app.state.settings.module4_enabled = enabled
    provider = Provider()
    client.app.state.module4_provider = provider
    base = f"/projects/{project_id}"
    item = client.post(base + "/items", headers=headers, json={"title": "Review"}).json()
    url = base + "/items/" + item["id"] + "/code-reviews"
    listing = client.get(url, headers=headers)
    assert listing.status_code == 200
    assert listing.json() == {"items": [], "total": 0, "limit": 20, "offset": 0, "enabled": enabled}
    draft = {
        "request_id": str(uuid4()),
        "expected_version": 1,
        "arquivos": [{"caminho": "a.py", "conteudo": "print('private input')"}],
    }
    result = client.post(url, headers=headers, json=draft)
    assert result.status_code == (201 if enabled else 503), result.text
    if not enabled:
        assert provider.calls == 0
        return
    record = result.json()
    assert record["source"] == {"kind": "files", "files": ["a.py"], "pr_url": None}
    assert record["status_effect"] == "started" and record["item_version"] == 2
    assert client.post(url, headers=headers, json=draft).json() == record
    assert provider.calls == 1
    assert client.get(url + "/" + record["id"], headers=headers).json() == record
    assert client.get(url, headers=headers).json()["items"] == [record]
    assert client.get(url + "?limit=0", headers=headers).status_code == 422
    assert client.get(url).status_code == 401
    assert "private input" not in client.get(url, headers=headers).text
    assert client.post(url, headers=headers, json={**draft, "usar_ia": True}).status_code == 409


@pytest.mark.parametrize("revocation", ["session", "permissions", "archived", "lease"])
def test_review_api_rechecks_current_access_after_provider(expanded_client, project_id, revocation):
    client, state, headers = expanded_client
    client.app.state.settings.module4_enabled = True
    base = f"/projects/{project_id}"
    item = client.post(base + "/items", headers=headers, json={"title": "Review"}).json()
    url = base + "/items/" + item["id"] + "/code-reviews"

    def revoke():
        if revocation == "session":
            state["active"] = False
        elif revocation == "permissions":
            state["access"]["permissions"].remove("backlog:update_status")
            state["access"]["role_definitions"][0]["permissions"].remove("backlog:update_status")
        elif revocation == "archived":
            state["access"]["archived"] = True
            state["access"]["project_status"] = "completed"
        else:
            state["lease_status"] = 409

    client.app.state.module4_provider = Provider(callback=revoke)
    result = client.post(
        url,
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_version": 1,
            "arquivos": [{"caminho": "a.py", "conteudo": "pass"}],
        },
    )
    assert result.status_code in {401, 403, 409}
    assert "markdown" not in result.text
    state["active"] = True
    state["access"]["archived"] = False
    state["access"]["project_status"] = "active"
    record = client.get(url, headers=headers).json()["items"][0]
    assert record["status_effect"] == "not_applied_access"
    assert record["result"] is not None
    assert client.get(base + "/items/" + item["id"], headers=headers).json()["status"] == "todo"


def test_module4_config_secret_defaults_validation_and_redaction():
    from pydantic import ValidationError

    from backlog_service.config import Settings

    assert not Settings(_env_file=None, database_url="sqlite:///:memory:").module4_enabled
    secret = "synthetic-private-module4"
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///:memory:",
        module4_enabled=True,
        module4_username="reviewer",
        module4_password=secret,
    )
    assert secret not in repr(settings)
    for values in [
        {"module4_enabled": True},
        {"module4_base_url": "https://example.com"},
        {"module4_username": "user:name"},
        {"module4_password": "line\nprivate"},
    ]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, database_url="sqlite:///:memory:", **values)


@pytest.mark.parametrize("delay", [0, 1])
def test_full_api_uses_real_tcp_provider_and_never_resends_uncertain(
    expanded_client, project_id, delay
):
    from test_module4_client import PASSWORD, owner_server

    from backlog_service.module4_client import Module4Client

    client, state, headers = expanded_client
    client.app.state.settings.module4_enabled = True
    base = f"/projects/{project_id}"
    item = client.post(base + "/items", headers=headers, json={"title": "TCP review"}).json()
    url = base + "/items/" + item["id"] + "/code-reviews"
    draft = {
        "request_id": str(uuid4()),
        "expected_version": 1,
        "arquivos": [{"caminho": "sample.py", "conteudo": "pass"}],
    }
    with owner_server(delay=delay) as (provider_url, calls):
        client.app.state.module4_provider = Module4Client(
            provider_url, "reviewer", PASSWORD, timeout=0.4 if delay else 60
        )
        result = client.post(url, headers=headers, json=draft)
        assert result.status_code == 201
        assert result.json()["status"] == ("uncertain" if delay else "succeeded")
        assert client.post(url, headers=headers, json=draft).json() == result.json()
        assert len(calls) == 1
        assert calls[0][1]["Authorization"].startswith("Basic ")
        assert headers["Authorization"] not in str(calls)
        assert "request_id" not in calls[0][2] and "expected_version" not in calls[0][2]
    actual = client.get(base + "/items/" + item["id"], headers=headers).json()
    assert actual["status"] == ("todo" if delay else "in_progress")


def test_jwks_unavailable_during_post_io_revalidation_is_sanitized_503(
    expanded_client, project_id, monkeypatch
):
    from backlog_service.security import SigningKeysUnavailable

    client, state, headers = expanded_client
    client.app.state.settings.module4_enabled = True
    base = f"/projects/{project_id}"
    item = client.post(base + "/items", headers=headers, json={"title": "JWKS review"}).json()
    url = base + "/items/" + item["id"] + "/code-reviews"
    failed = False
    original = client.app.state.verifier.verify

    def verify(token):
        if failed:
            raise SigningKeysUnavailable("synthetic private upstream detail")
        return original(token)

    monkeypatch.setattr(client.app.state.verifier, "verify", verify)

    def provider_finished():
        nonlocal failed
        failed = True

    client.app.state.module4_provider = Provider(callback=provider_finished)
    result = client.post(
        url,
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_version": 1,
            "arquivos": [{"caminho": "a.py", "conteudo": "pass"}],
        },
    )
    assert result.status_code == 503
    assert result.json() == {"detail": "Service temporarily unavailable"}
    failed = False
    stored = client.get(url, headers=headers).json()["items"][0]
    assert stored["status_effect"] == "not_applied_access" and stored["result"] is not None
    assert client.get(base + "/items/" + item["id"], headers=headers).json()["status"] == "todo"
