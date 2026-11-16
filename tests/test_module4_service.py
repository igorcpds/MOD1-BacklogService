# ruff: noqa: F811
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from story_context import context_for
from test_module4_client import BODY
from test_module6_notifications import m6_engine  # noqa: F401

from backlog_service.domain import (
    Conflict,
    DependencyUnavailable,
    InsufficientProjectPermissions,
    ItemChange,
    ItemDraft,
)
from backlog_service.module4_domain import Module4Outcome, Module4Review, ReviewRequest
from backlog_service.module4_repository import Module4Repository
from backlog_service.module4_service import Module4Service
from backlog_service.repository import StoryRepository
from backlog_service.service import StoriesService


class Provider:
    def __init__(self, callback=None, outcome=None):
        self.calls = 0
        self.callback = callback
        self.outcome = outcome or Module4Outcome(
            "succeeded", review=Module4Review.model_validate_json(__import__("json").dumps(BODY))
        )

    def analyze(self, draft):
        self.calls += 1
        if self.callback:
            self.callback()
        return self.outcome


def request(**changes):
    return ReviewRequest.model_validate(
        {
            "request_id": str(uuid4()),
            "expected_version": 1,
            "arquivos": [{"caminho": "sample.py", "conteudo": "print('synthetic')"}],
            **changes,
        }
    )


def setup(engine, project_id, provider, fresh=None, enabled=True):
    session = Session(engine, expire_on_commit=False)
    ctx = context_for(project_id)
    items = StoriesService(StoryRepository(session))
    item = items.create_item(ctx, ItemDraft(title="Review item"))
    reviews = Module4Service(
        Module4Repository(session), provider, fresh or (lambda: ctx), enabled=enabled
    )
    return session, ctx, item, items, reviews


def test_pending_committed_before_provider_and_no_db_lock(engine, project_id):
    provider = Provider()
    session, ctx, item, items, reviews = setup(engine, project_id, provider)
    draft = request()

    def during_io():
        assert not session.in_transaction()
        with Session(engine) as other:
            stored = Module4Repository(other).by_request(project_id, item.id, draft.request_id)
            assert stored is not None and stored.status == "pending"
        with Session(engine, expire_on_commit=False) as other:
            StoriesService(StoryRepository(other)).create_item(ctx, ItemDraft(title="Concurrent"))

    provider.callback = during_io
    result = reviews.analyze(ctx, item.id, draft)
    assert result.status == "succeeded" and result.status_effect == "started"
    assert result.item_version == 2
    assert items.get_item(ctx, item.id).status == "in_progress"
    assert items.history(ctx, item.id)["items"][0]["diff"]["status"]["after"] == "in_progress"
    assert reviews.analyze(ctx, item.id, draft) == result
    assert provider.calls == 1
    with pytest.raises(Conflict):
        reviews.analyze(ctx, item.id, draft.model_copy(update={"usar_ia": True}))
    session.close()


@pytest.mark.parametrize("status", ["in_progress", "done"])
def test_completed_or_started_item_preserved(engine, project_id, status):
    session, ctx, item, items, reviews = setup(engine, project_id, Provider())
    item = items.update_item(ctx, item.id, ItemChange(status=status, expected_version=1))
    result = reviews.analyze(ctx, item.id, request(expected_version=2))
    assert result.status_effect == "preserved" and result.item_version == 2
    assert items.get_item(ctx, item.id).status == status
    assert items.history(ctx, item.id)["total"] == 2
    session.close()


def test_concurrent_item_change_keeps_result_without_status_change(engine, project_id):
    provider = Provider()
    session, ctx, item, items, reviews = setup(engine, project_id, provider)

    def edit():
        with Session(engine, expire_on_commit=False) as other:
            StoriesService(StoryRepository(other)).update_item(
                ctx, item.id, ItemChange(title="Changed", expected_version=1)
            )

    provider.callback = edit
    result = reviews.analyze(ctx, item.id, request())
    assert result.result is not None and result.status_effect == "not_applied_conflict"
    assert items.get_item(ctx, item.id).status == "todo"
    session.close()


def test_access_revoked_during_io_persists_but_never_returns_result(engine, project_id):
    def revoked():
        raise InsufficientProjectPermissions()

    session, ctx, item, items, reviews = setup(engine, project_id, Provider(), fresh=revoked)
    with pytest.raises(InsufficientProjectPermissions):
        reviews.analyze(ctx, item.id, request())
    stored = reviews.list(ctx, item.id)["items"][0]
    assert stored.result is not None and stored.status_effect == "not_applied_access"
    assert items.get_item(ctx, item.id).status == "todo"
    session.close()


@pytest.mark.parametrize("status", ["failed", "blocked", "uncertain"])
def test_provider_failure_preserves_item_and_replay(engine, project_id, status):
    provider = Provider(outcome=Module4Outcome(status, error="provider_response"))
    session, ctx, item, items, reviews = setup(engine, project_id, provider)
    draft = request()
    result = reviews.analyze(ctx, item.id, draft)
    assert result.status == status and result.status_effect == "not_applied_error"
    assert result.result is None
    assert items.get_item(ctx, item.id).version == 1
    assert reviews.analyze(ctx, item.id, draft).id == result.id
    assert provider.calls == 1
    session.close()


def test_stale_request_never_calls_provider(engine, project_id):
    provider = Provider()
    session, ctx, item, items, reviews = setup(engine, project_id, provider)
    with pytest.raises(Conflict):
        reviews.analyze(ctx, item.id, request(expected_version=2))
    assert provider.calls == 0 and reviews.list(ctx, item.id)["total"] == 0
    session.close()


def test_scoped_reads_disabled_and_crashed_pending_never_retried(engine, project_id):
    provider = Provider(callback=lambda: (_ for _ in ()).throw(RuntimeError("crash")))
    session, ctx, item, items, reviews = setup(engine, project_id, provider)
    draft = request()
    with pytest.raises(RuntimeError):
        reviews.analyze(ctx, item.id, draft)
    assert reviews.analyze(ctx, item.id, draft).status == "pending"
    assert provider.calls == 1
    reviews.enabled = False
    assert reviews.list(ctx, item.id)["enabled"] is False
    with pytest.raises(DependencyUnavailable):
        reviews.analyze(ctx, item.id, request())
    other_item = items.create_item(ctx, ItemDraft(title="Other"))
    assert reviews.list(ctx, other_item.id)["total"] == 0
    from backlog_service.domain import MissingItem

    with pytest.raises(MissingItem):
        reviews.get(ctx, other_item.id, reviews.list(ctx, item.id)["items"][0].id)
    session.close()


def test_only_real_todo_transition_captures_existing_module6_notice(m6_engine, project_id):
    from sqlalchemy import select

    from backlog_service.models import NotificationDeliveryRecord

    session, ctx, item, items, reviews = setup(m6_engine, project_id, Provider())
    result = reviews.analyze(ctx, item.id, request())
    assert result.status_effect == "started"
    notices = session.scalars(select(NotificationDeliveryRecord)).all()
    assert [row.payload["type"] for row in notices].count("backlog.item.status_changed") == 1
    session.rollback()
    reviews.analyze(ctx, item.id, request(expected_version=2))
    assert len(session.scalars(select(NotificationDeliveryRecord)).all()) == len(notices)
    session.close()


def test_recheck_after_acquiring_final_lease_prevents_permission_race(engine, project_id):
    provider = Provider()
    calls = []
    session, ctx, item, items, reviews = setup(engine, project_id, provider)

    class Control:
        def acquire(self, project):
            calls.append("acquire")
            return uuid4()

        def release(self, project, lease):
            calls.append("release")

    def fresh():
        assert not session.in_transaction()
        if calls.count("acquire") == 2:
            raise InsufficientProjectPermissions()
        return ctx

    reviews.control = Control()
    reviews.fresh_context = fresh
    with pytest.raises(InsufficientProjectPermissions):
        reviews.analyze(ctx, item.id, request())
    assert calls == ["acquire", "release", "acquire", "release"]
    assert items.get_item(ctx, item.id).status == "todo"
    assert reviews.list(ctx, item.id)["items"][0].status_effect == "not_applied_access"
    session.close()


def test_failed_final_commit_rolls_back_status_history_and_preserves_provider_result(
    engine, project_id, monkeypatch
):
    session, ctx, item, items, reviews = setup(engine, project_id, Provider())
    original = reviews.repository.commit
    calls = 0

    def commit():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("synthetic commit failure")
        return original()

    monkeypatch.setattr(reviews.repository, "commit", commit)
    with pytest.raises(RuntimeError):
        reviews.analyze(ctx, item.id, request())
    stored = reviews.list(ctx, item.id)["items"][0]
    assert stored.result is not None
    assert stored.status_effect == "not_applied_error"
    assert items.get_item(ctx, item.id).status == "todo"
    assert items.history(ctx, item.id)["total"] == 1
    session.close()
