import os
from uuid import uuid4

import pytest
from postgresql_support import require_local
from sqlalchemy.orm import Session
from sqlalchemy.schema import DropSchema

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
            story = service.create(a, actor, StoryDraft(title="Entrega"))
            service.create(b, actor, StoryDraft(title="Outro projeto"))
            service.update(a, story.id, StoryChange(priority="high", status="done"))
        engine.dispose()
        with Session(engine) as session:
            repository = StoryRepository(session)
            page = repository.list_for_project(a, limit=20, offset=0)
            assert page.total == 1 and page.items[0].id == story.id
            assert (page.items[0].priority, page.items[0].status) == ("high", "done")
            assert repository.get_for_project(b, story.id) is None
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
