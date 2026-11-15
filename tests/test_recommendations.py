from uuid import uuid4

import pytest
from story_context import context_for

from backlog_service.domain import Conflict, DependencyUnavailable
from backlog_service.recommendation_service import RecommendationsService


class Source:
    def __init__(self, project_id):
        self.value = {
            "id": str(project_id),
            "description": "Actual authorized description",
            "version": 1,
        }

    def get(self, project_id):
        return self.value.copy()


class Provider:
    model = "synthetic-model"
    provider = "controlled-test-provider"
    simulated = True

    def __init__(self):
        self.context = None
        self.output = {
            "summary": "Initial backlog",
            "justification": "From project requirements",
            "evidence": ["project.description"],
            "suggestions": [{"title": "First delivery", "description": "Human approval required"}],
        }

    def generate(self, kind, context):
        self.context = context
        return self.output


def test_recommendation_uses_real_source_and_approval_is_atomic_idempotent(service, project_id):
    source, provider = Source(project_id), Provider()
    recs = RecommendationsService(service, source, provider)
    ctx = context_for(project_id)
    rec = recs.generate(ctx)
    assert provider.context["project"]["description"] == source.value["description"]
    assert rec.status == "pending" and rec.simulated and service.items(ctx).total == 0
    assert service.content_summary(ctx)["total"] > 0
    approved = recs.decide(ctx, rec.id, 1, approve=True)
    board_version = service.board(ctx)["version"]
    repeated = recs.decide(ctx, rec.id, 1, approve=True)
    assert service.board(ctx)["version"] == board_version
    assert approved.status == "approved" and repeated == approved
    assert service.items(ctx).total == 1
    assert len(approved.applied_item_ids) == 1
    assert service.history(ctx, approved.applied_item_ids[0])["total"] == 1


def test_stale_recommendation_expires_and_reject_never_creates(service, project_id):
    source, provider = Source(project_id), Provider()
    recs = RecommendationsService(service, source, provider)
    ctx = context_for(project_id)
    rec = recs.generate(ctx)
    source.value["version"] = 2
    with pytest.raises(Conflict):
        recs.decide(ctx, rec.id, 1, approve=True)
    assert recs.get(ctx, rec.id).status == "expired"
    assert service.items(ctx).total == 0
    other = recs.generate(ctx)
    assert recs.decide(ctx, other.id, 1, approve=False).status == "rejected"
    assert service.items(ctx).total == 0


@pytest.mark.parametrize(
    "change",
    [
        {"evidence": ["users." + str(uuid4())]},
        {"suggestions": [{"title": "Invalid", "assignee_id": str(uuid4())}]},
        {"suggestions": [{"title": "Invalid", "kind": "task"}]},
    ],
)
def test_untrusted_provider_output_fails_closed(service, project_id, change):
    provider = Provider()
    provider.output.update(change)
    recs = RecommendationsService(service, Source(project_id), provider)
    with pytest.raises(DependencyUnavailable):
        recs.generate(context_for(project_id))
    assert service.items(context_for(project_id)).total == 0


def test_concurrent_approval_creates_suggestions_once(engine, service, project_id):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import Session

    from backlog_service.repository import StoryRepository
    from backlog_service.service import StoriesService

    source, provider = Source(project_id), Provider()
    ctx = context_for(project_id)
    rec = RecommendationsService(service, source, provider).generate(ctx)
    barrier = Barrier(2)

    def approve(_):
        with Session(engine, expire_on_commit=False) as session:
            worker = RecommendationsService(
                StoriesService(StoryRepository(session)), source, provider
            )
            barrier.wait()
            return worker.decide(ctx, rec.id, 1, approve=True)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(approve, range(2)))
    assert results[0] == results[1]
    assert service.items(ctx).total == 1


def test_empty_proposal_is_readable_rejectable_but_cannot_be_approved(service, project_id):
    provider = Provider()
    provider.output["suggestions"] = []
    recs = RecommendationsService(service, Source(project_id), provider)
    ctx = context_for(project_id)
    rec = recs.generate(ctx)
    assert rec.suggestions == [] and rec.status == "pending"
    board = service.board(ctx)
    history = service.content_summary(ctx)
    with pytest.raises(Conflict, match="no suggestions"):
        recs.decide(ctx, rec.id, 1, approve=True)
    assert service.items(ctx).total == 0
    assert service.board(ctx) == board
    assert service.content_summary(ctx) == history
    assert recs.get(ctx, rec.id) == rec
    assert recs.decide(ctx, rec.id, 1, approve=False).status == "rejected"


@pytest.mark.parametrize(
    "change",
    [
        {"evidence": ["project.invented"]},
        {"evidence": ["items." + str(uuid4())]},
        {"suggestions": [{"title": "Bad", "epic_id": str(uuid4())}]},
    ],
)
def test_gemini_invented_references_leave_no_proposal_or_items(service, project_id, change):
    import httpx
    from test_gemini_adapter import PROPOSAL, envelope, provider

    ai = provider(lambda _: httpx.Response(200, json=envelope({**PROPOSAL, **change})))
    recs = RecommendationsService(service, Source(project_id), ai)
    ctx = context_for(project_id)
    before = service.content_summary(ctx)
    with pytest.raises(DependencyUnavailable):
        recs.generate(ctx)
    assert recs.list(ctx)["total"] == 0
    assert service.items(ctx).total == 0
    assert service.content_summary(ctx) == before
