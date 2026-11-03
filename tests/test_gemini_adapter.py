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


def test_gemini_accepts_empty_and_ignores_thought_text():
    expected = {**PROPOSAL, "suggestions": []}
    result = envelope(expected)
    result["candidates"][0]["content"]["parts"].insert(0, {"thought": True, "text": "private"})
    assert (
        provider(lambda _: httpx.Response(200, json=result)).generate("initial_backlog", CONTEXT)
        == expected
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
