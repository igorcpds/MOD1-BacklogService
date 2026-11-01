from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event as sql_event
from story_context import context_for

from backlog_service.domain import (
    Conflict,
    DependencyUnavailable,
    InsufficientProjectPermissions,
    ItemChange,
    ItemDraft,
    ReviewEvent,
    ReviewPrincipal,
)
from backlog_service.review_service import ReviewService


def review_event(context, item, **changes):
    values = dict(
        schema_version=1,
        event_id=uuid4(),
        project_id=context.project_id,
        item_id=item.id,
        event_type="locally_agreed_merge",
        occurred_at=datetime(2026, 10, 11, tzinfo=UTC),
        expected_item_version=item.version,
    )
    return ReviewEvent(**(values | changes))


def review_service(service, project_id):
    return ReviewService(
        service,
        {"locally_agreed_merge": "done"},
        ReviewPrincipal("code-review", frozenset({project_id})),
    )


def test_review_is_atomic_idempotent_and_records_integration_origin(service, project_id):
    ctx = context_for(project_id)
    item = service.create_item(ctx, ItemDraft(title="Human authored"))
    review = review_service(service, project_id)
    event = review_event(ctx, item)
    result = review.apply(ctx, event)
    assert result["status"] == "done" and result["item_version"] == 2
    board_version = service.board(ctx)["version"]
    assert review.apply(ctx, event) == result
    assert service.board(ctx)["version"] == board_version
    saved = service.get_item(ctx, item.id)
    assert saved.status == "done" and saved.title == item.title and saved.version == 2
    history = service.history(ctx, item.id)
    assert history["total"] == 2
    assert history["items"][0]["action"] == "code_review"
    assert history["items"][0]["diff"]["integration"]["principal"] == "code-review"
    with pytest.raises(Conflict):
        review.apply(ctx, event.model_copy(update={"expected_item_version": 2}))
    assert service.get_item(ctx, item.id).version == 2


def test_review_rejects_older_event_and_manual_conflict(service, project_id):
    ctx = context_for(project_id)
    item = service.create_item(ctx, ItemDraft(title="Manual"))
    review = review_service(service, project_id)
    first = review_event(ctx, item)
    review.apply(ctx, first)
    current = service.get_item(ctx, item.id)
    with pytest.raises(Conflict):
        review.apply(
            ctx, review_event(ctx, current, occurred_at=first.occurred_at - timedelta(seconds=1))
        )
    manual = service.update_item(ctx, item.id, ItemChange(status="todo", expected_version=2))
    with pytest.raises(Conflict):
        review.apply(
            ctx, review_event(ctx, current, occurred_at=first.occurred_at + timedelta(seconds=1))
        )
    assert service.get_item(ctx, item.id) == manual


def test_review_scope_and_unconfigured_mapping_deny_before_sql(engine, service, project_id):
    ctx = context_for(project_id)
    item = service.create_item(ctx, ItemDraft(title="Protected"))
    draft = review_event(ctx, item)
    statements = []
    sql_event.listen(
        engine, "before_cursor_execute", lambda c, cur, sql, p, ec, many: statements.append(sql)
    )
    with pytest.raises(DependencyUnavailable):
        ReviewService(service, {}, ReviewPrincipal("code-review", frozenset({project_id}))).apply(
            ctx, draft
        )
    with pytest.raises(InsufficientProjectPermissions):
        ReviewService(
            service,
            {"locally_agreed_merge": "done"},
            ReviewPrincipal("code-review", frozenset({uuid4()})),
        ).apply(ctx, draft)
    with pytest.raises(InsufficientProjectPermissions):
        review_service(service, project_id).apply(
            ctx, draft.model_copy(update={"project_id": uuid4()})
        )
    assert statements == []


def test_review_receipt_failure_rolls_back_item_and_history(service, project_id, monkeypatch):
    ctx = context_for(project_id)
    item = service.create_item(ctx, ItemDraft(title="Atomic"))
    review = review_service(service, project_id)
    draft = review_event(ctx, item)

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("synthetic receipt persistence failure")

    monkeypatch.setattr(service.repository, "save_review_event", fail_receipt)
    with pytest.raises(RuntimeError):
        review.apply(ctx, draft)
    assert service.get_item(ctx, item.id) == item
    assert service.history(ctx, item.id)["total"] == 1
    assert service.repository.review_event(project_id, draft.event_id) is None


def test_concurrent_review_replay_applies_once(engine, service, project_id):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import Session

    from backlog_service.repository import StoryRepository
    from backlog_service.service import StoriesService

    ctx = context_for(project_id)
    item = service.create_item(ctx, ItemDraft(title="Concurrent receipt"))
    draft = review_event(ctx, item)
    barrier = Barrier(2)

    def apply(_):
        with Session(engine, expire_on_commit=False) as session:
            items = StoriesService(StoryRepository(session), clock=service.clock)
            barrier.wait()
            return review_service(items, project_id).apply(ctx, draft)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(apply, range(2)))
    assert results[0] == results[1]
    assert service.get_item(ctx, item.id).version == 2
    assert service.history(ctx, item.id)["total"] == 2
    summary = service.content_summary(ctx)
    assert summary["review_events"] == 1 and summary["total"] == 4
