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
