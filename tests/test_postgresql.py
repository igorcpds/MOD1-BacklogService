import os
from uuid import uuid4

import pytest
from postgresql_support import require_local
from sqlalchemy.orm import Session
from sqlalchemy.schema import DropSchema
from story_context import context_for

from backlog_service.config import Settings
from backlog_service.database import create_database_engine, init_schema
from backlog_service.domain import StoryChange, StoryDraft
from backlog_service.repository import StoryRepository
from backlog_service.service import StoriesService


def test_disposable_postgresql_persistence_and_project_isolation():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL loopback not configured; never run against Neon")
    require_local(url)
    schema = "test_backlog_" + uuid4().hex
    settings = Settings(database_url=url, database_schema=schema, _env_file=None)
    engine = create_database_engine(settings)
    a, b, actor = uuid4(), uuid4(), uuid4()
    try:
        init_schema(engine, schema)
        with Session(engine) as session:
            service = StoriesService(StoryRepository(session))
            story = service.create(context_for(a, actor), StoryDraft(title="Entrega"))
            service.create(context_for(b, actor), StoryDraft(title="Outro projeto"))
            updated = service.update(
                context_for(a),
                story.id,
                StoryChange(
                    title=" Entrega ÁRVORE ",
                    description="100% a_b!",
                    acceptance_criteria="Critério\nverificável",
                    priority="high",
                    status="done",
                ),
            )
            service.create(context_for(a, actor), StoryDraft(title="Entrega 100x axb"))
        engine.dispose()
        with Session(engine) as session:
            repository = StoryRepository(session)
            page = repository.list_for_project(
                a, limit=20, offset=0, q="árvore", priority="high", status="done"
            )
            assert page.total == 1 and page.items[0].id == story.id
            assert (page.items[0].priority, page.items[0].status) == ("high", "done")
            assert page.items[0] == updated
            service = StoriesService(repository)
            assert service.list(context_for(a), q="100%", priority="high", status="done").total == 1
            assert service.list(context_for(a), q="a_b!").total == 1
            assert service.list(context_for(a), q=str(story.id).upper()).items == [updated]
            assert service.list(context_for(a), q="entrega", limit=1, offset=1).total == 2
            assert repository.get_for_project(b, story.id) is None
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def test_disposable_postgresql_expanded_migration_graph_reorder_and_event_replay():
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime
    from threading import Barrier

    from sqlalchemy import text
    from sqlalchemy.schema import CreateSchema
    from test_recommendations import Provider, Source

    from backlog_service.domain import (
        Conflict,
        ItemDraft,
        ProjectContext,
        Reorder,
        ReviewEvent,
        ReviewPrincipal,
    )
    from backlog_service.recommendation_service import RecommendationsService
    from backlog_service.review_service import ReviewService

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL loopback not configured; never run against Neon")
    require_local(url)
    schema = "test_backlog_" + uuid4().hex
    settings = Settings(database_url=url, database_schema=schema, _env_file=None)
    engine = create_database_engine(settings)
    project, actor, legacy = uuid4(), uuid4(), uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".stories ('
                    "id UUID PRIMARY KEY, project_id UUID NOT NULL, created_by UUID NOT NULL, "
                    "title VARCHAR(120) NOT NULL, description TEXT NOT NULL, "
                    "acceptance_criteria TEXT NOT NULL, "
                    "priority VARCHAR(10) NOT NULL, status VARCHAR(20) NOT NULL, "
                    "created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)"
                )
            )
            connection.execute(
                text(
                    f'INSERT INTO "{schema}".stories VALUES '
                    "(:id,:project,:actor,'Legacy','Preserved','Acceptance','high','todo',:now,:now)"
                ),
                {"id": legacy, "project": project, "actor": actor, "now": datetime.now(UTC)},
            )
        init_schema(engine, schema)
        init_schema(engine, schema)
        old = context_for(project, actor)
        ctx = ProjectContext(project, actor, old.permissions | {"backlog:reorder"})
        with Session(engine, expire_on_commit=False) as session:
            service = StoriesService(StoryRepository(session))
            migrated = service.get_item(ctx, legacy)
            assert migrated.kind == "story" and migrated.moscow_priority is None
            assert (
                migrated.description == "Preserved" and service.history(ctx, legacy)["total"] == 0
            )
            epic = service.create_item(ctx, ItemDraft(title="Epic", kind="epic"))
            task = service.create_item(
                ctx, ItemDraft(title="Task", kind="task", parent_story_id=legacy)
            )
            service.add_dependency(ctx, task.id, legacy)
            with pytest.raises(Conflict):
                service.add_dependency(ctx, legacy, task.id)
            version = service.board(ctx)["version"]
            service.reorder(
                ctx, Reorder(item_ids=[task.id, legacy, epic.id], expected_version=version)
            )
            recs = RecommendationsService(service, Source(project), Provider())
            recommendation = recs.generate(ctx)
            approved = recs.decide(ctx, recommendation.id, 1, approve=True)
            assert len(approved.applied_item_ids) == 1
            target = service.get_item(ctx, legacy)
            service.repository.rollback()
        draft = ReviewEvent(
            schema_version=1,
            event_id=uuid4(),
            project_id=project,
            item_id=legacy,
            occurred_at=datetime.now(UTC),
            event_type="local_merge",
            expected_item_version=target.version,
        )
        barrier = Barrier(2)

        def apply(_):
            with Session(engine, expire_on_commit=False) as session:
                worker = StoriesService(StoryRepository(session))
                barrier.wait()
                return ReviewService(
                    worker,
                    {"local_merge": "done"},
                    ReviewPrincipal("code-review", frozenset({project})),
                ).apply(ctx, draft)

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(apply, range(2)))
        assert results[0] == results[1]
        with Session(engine) as session:
            service = StoriesService(StoryRepository(session))
            assert service.get_item(ctx, legacy).status == "done"
            assert service.content_summary(ctx)["review_events"] == 1
            assert service.items(context_for(uuid4())).total == 0
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
