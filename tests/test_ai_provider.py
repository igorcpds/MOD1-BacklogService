import httpx
import pytest

from backlog_service.ai_provider import HTTPProposalProvider
from backlog_service.domain import DependencyUnavailable


def test_ai_disabled_never_calls_provider(settings):
    def fail(request):
        pytest.fail("Disabled provider must not be called")

    provider = HTTPProposalProvider(httpx.Client(transport=httpx.MockTransport(fail)), settings)
    with pytest.raises(DependencyUnavailable):
        provider.generate("initial_backlog", {"project": {"description": "Requirements"}})


def test_ai_http_contract_bounded_and_labeled(settings):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "summary": "Draft",
                "justification": "Project scope",
                "evidence": ["project.description"],
                "suggestions": [{"title": "First story"}],
            },
        )

    configured = settings.model_copy(
        update={
            "ai_base_url": "http://127.0.0.1:9900",
            "ai_model": "local-test",
            "ai_simulated": True,
        }
    )
    provider = HTTPProposalProvider(
        httpx.Client(transport=httpx.MockTransport(respond)), configured
    )
    assert (
        provider.generate("initial_backlog", {"project": {"description": "Requirements"}})[
            "summary"
        ]
        == "Draft"
    )
    assert calls[0].url.path == "/generate" and provider.simulated
    with pytest.raises(DependencyUnavailable):
        provider.generate("initial_backlog", {"oversized": "x" * 65537})


def test_generic_http_preserves_its_existing_broader_story_contract(settings):
    from backlog_service.domain import GeneratedProposal

    output = {
        "summary": "Existing generic proposal",
        "justification": "Existing generic contract",
        "evidence": ["project.description"],
        "suggestions": [
            {
                "title": "Existing generic story",
                "estimate_value": "5",
                "estimate_unit": "hours",
                "is_blocked": True,
                "blocked_reason": "Explicit generic contract value",
            }
        ],
    }
    configured = settings.model_copy(
        update={"ai_base_url": "http://127.0.0.1:9900", "ai_model": "test"}
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=output))
    ) as client:
        result = HTTPProposalProvider(client, configured).generate("initial_backlog", {})
    assert result == output
    story = GeneratedProposal.model_validate(result).suggestions[0]
    assert story.estimate_value == "5" and story.estimate_unit == "hours"
    assert story.is_blocked and story.blocked_reason == "Explicit generic contract value"
