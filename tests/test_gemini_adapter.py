import importlib
import json

import httpx
import pytest
from pydantic import ValidationError

from backlog_service.config import Settings
from backlog_service.domain import DependencyUnavailable

CONTEXT = {"project": {"description": "Portal sintético"}, "items": [], "constraints": {}}
PROPOSAL = {
    "summary": "Proposta inicial",
    "justification": "Descrição autorizada do projeto",
    "evidence": ["project.description"],
    "suggestions": [{"title": "Consultar o portal", "kind": "story"}],
}

OUT_OF_CONTRACT_STORY_FIELDS = [
    {"estimate_value": None},
    {"estimate_unit": None},
    {"is_blocked": False},
    {"blocked_reason": "Hidden from the review card"},
    {"moscow_priority": "must"},
    {"assignee_id": None},
    {"epic_id": None},
    {"parent_story_id": None},
    {
        "estimate_value": "999999",
        "estimate_unit": "hours",
        "is_blocked": True,
        "blocked_reason": "Invented",
    },
    {"unexpected": {"nested": "value"}},
]


def envelope(proposal=PROPOSAL):
    return {
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(proposal)}]}}
        ]
    }


def configured(**updates):
    return Settings(
        _env_file=None,
        database_url="sqlite:///:memory:",
        ai_provider="gemini",
        gemini_api_key="synthetic-only-key",
        **updates,
    )


def provider(handler, settings=None, *, foreign_headers=False):
    adapter = importlib.import_module("backlog_service.gemini_adapter").GeminiProposalProvider
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer foreign-user-token"} if foreign_headers else None,
        trust_env=False,
    )
    return adapter(client, settings or configured())


def test_gemini_config_is_explicit_and_secrets_hidden(settings):
    assert settings.ai_provider == "structured-http"
    config = configured()
    assert config.gemini_model == "gemini-3.5-flash-lite"
    assert config.gemini_timeout_seconds == 30
    assert config.gemini_max_output_tokens == 4096
    assert config.gemini_api_base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert "synthetic-only-key" not in repr(config)


@pytest.mark.parametrize(
    "updates",
    [
        {"ai_provider": "unknown"},
        {"ai_simulated": True, "ai_base_url": "http://127.0.0.1:9999"},
        {"gemini_timeout_seconds": 0},
        {"gemini_timeout_seconds": 31},
        {"gemini_max_output_tokens": 255},
        {"gemini_max_output_tokens": 8193},
        {"gemini_model": "../other"},
        {"gemini_model": "name?key=value"},
        {"gemini_model": "model%2Fescape"},
        {"gemini_api_base_url": "https://attacker.test/v1beta"},
        {"gemini_api_base_url": "http://generativelanguage.googleapis.com/v1beta"},
        {"gemini_api_base_url": "https://generativelanguage.googleapis.com:444/v1beta"},
        {"gemini_api_base_url": "https://user@generativelanguage.googleapis.com/v1beta"},
        {"gemini_api_base_url": "https://generativelanguage.googleapis.com/v1beta?x=1"},
        {"gemini_api_base_url": "https://generativelanguage.googleapis.com/v1beta#frag"},
        {"gemini_api_base_url": "http://127.0.0.1:9999/a/../v1beta"},
        {"gemini_api_base_url": "http://127.0.0.1:9999/%2e%2e/v1beta"},
        {"gemini_api_base_url": "http://127.0.0.1:bad/v1beta"},
        {"gemini_api_base_url": "http://127.0.0.1:65536/v1beta"},
    ],
)
def test_gemini_config_rejects_untrusted_urls_and_unbounded_options(updates):
    values = {"ai_provider": "gemini", **updates}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite:///:memory:", **values)


@pytest.mark.parametrize(
    "base", ["http://127.0.0.1:9999/gemini/v1beta", "http://[::1]:9999/v1beta"]
)
def test_gemini_loopback_override_for_local_simulations(base):
    assert configured(gemini_api_base_url=base).gemini_api_base_url == base


def test_gemini_request_is_structured_portuguese_and_excludes_foreign_credentials():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=envelope())

    ai = provider(respond, foreign_headers=True)
    assert ai.generate("initial_backlog", CONTEXT) == PROPOSAL
    assert (ai.provider, ai.model, ai.simulated) == ("gemini", "gemini-3.5-flash-lite", False)
    request = requests[0]
    assert (
        request.url
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
    )
    assert request.headers["x-goog-api-key"] == "synthetic-only-key"
    assert "authorization" not in request.headers
    body = json.loads(request.content)
    assert json.loads(body["contents"][0]["parts"][0]["text"]) == {
        "kind": "initial_backlog",
        "context": CONTEXT,
    }
    assert body["contents"][0]["role"] == "user"
    prompt = body["systemInstruction"]["parts"][0]["text"]
    assert "não confiáveis" in prompt and "items.UUID" in prompt and "project." in prompt
    generation = body["generationConfig"]
    assert generation["candidateCount"] == 1 and generation["maxOutputTokens"] == 4096
    text = generation["responseFormat"]["text"]
    assert text["mimeType"] == "APPLICATION_JSON"
    schema = text["schema"]
    assert set(schema["required"]) == {"summary", "justification", "evidence", "suggestions"}
    assert schema["properties"]["suggestions"]["items"]["properties"]["kind"]["enum"] == ["story"]
    assert "tools" not in body and "responseMimeType" not in generation
    assert request.extensions["timeout"]["read"] == 30


def test_gemini_does_not_inherit_client_auth_cookies_or_query_parameters():
    adapter = importlib.import_module("backlog_service.gemini_adapter").GeminiProposalProvider
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=envelope())

    with httpx.Client(
        transport=httpx.MockTransport(respond),
        headers={"Authorization": "Bearer synthetic-user-token"},
        auth=httpx.BasicAuth("synthetic-user", "synthetic-password"),
        cookies={"session": "synthetic-session"},
        params={"token": "synthetic-query-token"},
        trust_env=False,
    ) as client:
        assert adapter(client, configured()).generate("initial_backlog", CONTEXT) == PROPOSAL
    assert len(requests) == 1
    assert "authorization" not in requests[0].headers
    assert "cookie" not in requests[0].headers
    assert not requests[0].url.query
    assert requests[0].headers["x-goog-api-key"] == "synthetic-only-key"
    assert requests[0].extensions["timeout"]["read"] == 30


def test_gemini_accepts_empty_and_ignores_thought_text():
    expected = {**PROPOSAL, "suggestions": []}
    result = envelope(expected)
    result["candidates"][0]["content"]["parts"].insert(0, {"thought": True, "text": "private"})
    assert (
        provider(lambda _: httpx.Response(200, json=result)).generate("initial_backlog", CONTEXT)
        == expected
    )


@pytest.mark.parametrize("extra", OUT_OF_CONTRACT_STORY_FIELDS)
def test_gemini_rejects_story_fields_outside_advertised_schema(extra):
    output = {**PROPOSAL, "suggestions": [{**PROPOSAL["suggestions"][0], **extra}]}
    with pytest.raises(DependencyUnavailable, match="unavailable or invalid"):
        provider(lambda _: httpx.Response(200, json=envelope(output))).generate(
            "initial_backlog", CONTEXT
        )


@pytest.mark.parametrize(
    "story",
    [
        {"title": "Required kind is missing"},
        {"kind": "story", "title": "Story", "guided": 1},
        {"kind": "story", "title": "Story", "priority": "urgent"},
        {"kind": "story", "title": "Story", "description": None},
        {"kind": "story", "title": "Story", "title_extra": {}},
    ],
)
def test_gemini_enforces_required_fields_and_strict_schema_types(story):
    output = {**PROPOSAL, "suggestions": [story]}
    with pytest.raises(DependencyUnavailable):
        provider(lambda _: httpx.Response(200, json=envelope(output))).generate(
            "initial_backlog", CONTEXT
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", ""),
        ("title", "x" * 121),
        ("description", "x" * 2001),
        ("acceptance_criteria", "x" * 2001),
        ("persona", "x" * 501),
        ("action", "x" * 501),
        ("benefit", "x" * 501),
    ],
)
def test_gemini_enforces_advertised_story_string_bounds(field, value):
    story = {**PROPOSAL["suggestions"][0], field: value}
    output = {**PROPOSAL, "suggestions": [story]}
    with pytest.raises(DependencyUnavailable):
        provider(lambda _: httpx.Response(200, json=envelope(output))).generate(
            "initial_backlog", CONTEXT
        )


def test_gemini_rejects_top_level_extra_fields():
    output = {**PROPOSAL, "unexpected": {"nested": "value"}}
    with pytest.raises(DependencyUnavailable):
        provider(lambda _: httpx.Response(200, json=envelope(output))).generate(
            "initial_backlog", CONTEXT
        )


def test_gemini_preserves_all_valid_story_fields_without_inserting_hidden_defaults():
    story = {
        "kind": "story",
        "title": "Consultar solicitações",
        "description": "Consulta autenticada",
        "acceptance_criteria": "Apenas solicitações próprias são exibidas.",
        "priority": "high",
        "persona": "cliente",
        "action": "consultar minhas solicitações",
        "benefit": "acompanhar o atendimento",
        "guided": True,
    }
    output = {**PROPOSAL, "suggestions": [story]}
    assert (
        provider(lambda _: httpx.Response(200, json=envelope(output))).generate(
            "initial_backlog", CONTEXT
        )
        == output
    )


@pytest.mark.parametrize("status", [302, 429, 500, 503])
def test_gemini_http_failures_are_sanitized_without_retries(status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://attacker.test"}, text="secret")

    with pytest.raises(DependencyUnavailable, match="unavailable or invalid") as error:
        provider(respond).generate("initial_backlog", CONTEXT)
    assert len(requests) == 1 and "secret" not in str(error.value)


@pytest.mark.parametrize(
    "result",
    [
        {},
        [],
        {"candidates": []},
        {"candidates": envelope()["candidates"] * 2},
        {"promptFeedback": {"blockReason": "SAFETY"}, **envelope()},
        {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}]},
        {
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"functionCall": {"name": "bad"}}]}}
            ]
        },
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{"}]}}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "[]"}]}}]},
        {
            "candidates": [
                {"finishReason": "STOP", "content": {"parts": [{"thought": True, "text": "{}"}]}}
            ]
        },
        envelope(
            {
                **PROPOSAL,
                "suggestions": [
                    {"title": "Bad", "assignee_id": "11111111-1111-4111-8111-111111111111"}
                ],
            }
        ),
    ],
)
def test_gemini_rejects_blocked_truncated_malformed_and_tool_outputs(result):
    with pytest.raises(DependencyUnavailable):
        provider(lambda _: httpx.Response(200, json=result)).generate("initial_backlog", CONTEXT)


def test_gemini_bounds_context_response_and_does_not_send_missing_key():
    def fail(request):
        pytest.fail("Invalid input must never issue a request")

    with pytest.raises(DependencyUnavailable):
        provider(fail).generate("initial_backlog", {"description": "x" * 65537})
    with pytest.raises(DependencyUnavailable):
        provider(fail).generate("other", CONTEXT)
    with pytest.raises(DependencyUnavailable):
        provider(fail, configured().model_copy(update={"gemini_api_key": None})).generate(
            "initial_backlog", CONTEXT
        )
    with pytest.raises(DependencyUnavailable):
        provider(lambda _: httpx.Response(200, content=b"x" * 262145)).generate(
            "initial_backlog", CONTEXT
        )


def test_gemini_timeout_is_sanitized_without_retry():
    requests = []

    def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout("synthetic-only-key", request=request)

    with pytest.raises(DependencyUnavailable) as error:
        provider(timeout).generate("initial_backlog", CONTEXT)
    assert len(requests) == 1 and "synthetic-only-key" not in str(error.value)


def test_gemini_rejects_blocked_prompt_safety_rating_even_with_stop():
    result = {"promptFeedback": {"safetyRatings": [{"blocked": True}]}, **envelope()}
    with pytest.raises(DependencyUnavailable):
        provider(lambda _: httpx.Response(200, json=result)).generate("initial_backlog", CONTEXT)


def test_gemini_rejects_malformed_thought_marker():
    result = envelope()
    result["candidates"][0]["content"]["parts"][0]["thought"] = "true"
    with pytest.raises(DependencyUnavailable):
        provider(lambda _: httpx.Response(200, json=result)).generate("initial_backlog", CONTEXT)


@pytest.mark.parametrize("nested_location", ["envelope", "proposal"])
def test_gemini_deep_json_is_sanitized_without_retry(nested_location):
    nested = "[" * 4000 + "0" + "]" * 4000
    if nested_location == "envelope":
        body = nested.encode()
    else:
        result = envelope()
        result["candidates"][0]["content"]["parts"][0]["text"] = nested
        body = json.dumps(result).encode()
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=body)

    with pytest.raises(DependencyUnavailable, match="unavailable or invalid"):
        provider(respond).generate("initial_backlog", CONTEXT)
    assert len(calls) == 1


def test_app_selects_gemini_explicitly_and_keeps_generic_default(settings):
    from backlog_service.ai_provider import HTTPProposalProvider
    from backlog_service.app import create_app

    generic = create_app(settings)
    gemini = create_app(configured())
    try:
        assert isinstance(generic.state.ai_provider, HTTPProposalProvider)
        assert gemini.state.ai_provider.provider == "gemini"
    finally:
        generic.state.engine.dispose()
        gemini.state.engine.dispose()
