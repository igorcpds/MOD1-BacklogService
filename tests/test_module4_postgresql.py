"""Disposable loopback PostgreSQL: additive DDL, replay races and atomic status audit."""

import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Barrier, Event, Lock
from uuid import uuid4

import pytest
from postgresql_support import require_local
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import DropSchema
from story_context import context_for
from test_module4_service import Provider, request

from backlog_service.config import Settings
from backlog_service.database import create_database_engine, init_schema, migrate_schema
from backlog_service.domain import ItemDraft
from backlog_service.models import HistoryRecord, Module4ReviewRecord, NotificationDeliveryRecord
from backlog_service.module4_repository import Module4Repository
from backlog_service.module4_service import Module4Service
from backlog_service.repository import StoryRepository
from backlog_service.service import StoriesService


@pytest.fixture
def pg_review_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL loopback not configured; never use remote databases")
    require_local(url)
    schema = "test_module4_" + uuid4().hex
    settings = Settings(
        _env_file=None,
        database_url=url,
        database_schema=schema,
        module6_enabled=True,
        module6_key="synthetic-test-key",
    )
    engine = create_database_engine(settings)
    try:
        init_schema(engine, schema)
        yield engine, schema
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def test_pg_module4_additive_migration_preserves_items_and_runtime_has_no_ddl(pg_review_engine):
    engine, schema = pg_review_engine
    ctx = context_for(uuid4())
    with Session(engine) as session:
        item = StoriesService(StoryRepository(session)).create_item(ctx, ItemDraft(title="Keep"))
    Module4ReviewRecord.__table__.drop(engine)
    assert "module4_reviews" not in inspect(engine).get_table_names(schema=schema)
    migrate_schema(engine, schema)
    migrate_schema(engine, schema)
    assert "module4_reviews" in inspect(engine).get_table_names(schema=schema)
    with Session(engine) as session:
        assert Module4Repository(session).item(ctx.project_id, item.id).title == "Keep"
        assert session.scalar(select(func.count()).select_from(Module4ReviewRecord)) == 0


def test_pg_duplicate_same_request_has_one_external_post_and_restart_replay(pg_review_engine):
    engine, schema = pg_review_engine
    ctx = context_for(uuid4())
    with Session(engine) as session:
        item = StoriesService(StoryRepository(session)).create_item(ctx, ItemDraft(title="Race"))
    ready, release = Event(), Event()
    provider = Provider(callback=lambda: (ready.set(), release.wait(timeout=10)))
    draft = request()
    start = Barrier(2)

    def analyze():
        with Session(engine, expire_on_commit=False) as session:
            reviews = Module4Service(
                Module4Repository(session), provider, lambda: ctx, enabled=True
            )
            start.wait(timeout=10)
            return reviews.analyze(ctx, item.id, draft)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(analyze) for _ in range(2)]
        try:
            assert ready.wait(timeout=10)
            completed, _ = wait(futures, timeout=10, return_when=FIRST_COMPLETED)
            assert len(completed) == 1
            assert next(iter(completed)).result().status == "pending"
        finally:
            release.set()
        results = [future.result(timeout=10) for future in futures]
    assert len({result.id for result in results}) == 1 and provider.calls == 1
    engine.dispose()
    with Session(engine) as session:
        service = Module4Service(Module4Repository(session), provider, lambda: ctx, enabled=True)
        assert service.analyze(ctx, item.id, draft).status_effect == "started"
        assert provider.calls == 1
        assert session.scalar(select(func.count()).select_from(Module4ReviewRecord)) == 1
        assert service.repository.item(ctx.project_id, item.id).version == 2


def test_pg_competing_analyses_preserve_both_results_and_one_atomic_status_notice(pg_review_engine):
    engine, schema = pg_review_engine
    ctx = context_for(uuid4())
    with Session(engine) as session:
        item = StoriesService(StoryRepository(session)).create_item(ctx, ItemDraft(title="Race"))
    provider_barrier = Barrier(2)
    counter_lock = Lock()
    calls = []

    class ParallelProvider(Provider):
        def analyze(self, draft):
            with counter_lock:
                calls.append(draft)
            provider_barrier.wait(timeout=10)
            return self.outcome

    provider = ParallelProvider()

    def analyze(_):
        with Session(engine, expire_on_commit=False) as session:
            assert not session.in_transaction()
            service = Module4Service(
                Module4Repository(session), provider, lambda: ctx, enabled=True
            )
            return service.analyze(ctx, item.id, request())

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(analyze, range(2)))
    assert sorted(result.status_effect for result in results) == ["not_applied_conflict", "started"]
    assert all(result.result is not None and result.item_version == 2 for result in results)
    assert len(calls) == 2
    with Session(engine) as session:
        repository = Module4Repository(session)
        assert repository.item(ctx.project_id, item.id).status == "in_progress"
        assert repository.item(ctx.project_id, item.id).version == 2
        assert session.scalar(select(func.count()).select_from(HistoryRecord)) == 2
        notices = session.scalars(select(NotificationDeliveryRecord)).all()
        assert [record.payload["type"] for record in notices].count(
            "backlog.item.status_changed"
        ) == 1
        rows, total = repository.reviews(ctx.project_id, item.id, 20, 0)
        assert total == 2 and all(row.result is not None for row in rows)
