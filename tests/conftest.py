from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from backlog_service.config import Settings
from backlog_service.database import create_database_engine, init_schema
from backlog_service.repository import StoryRepository
from backlog_service.service import StoriesService


@pytest.fixture
def project_id():
    return UUID("11111111-1111-4111-8111-111111111111")


@pytest.fixture
def actor_id():
    return UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'stories.db'}")


@pytest.fixture
def engine(settings):
    engine = create_database_engine(settings)
    init_schema(engine, settings.database_schema)
    yield engine
    engine.dispose()


@pytest.fixture
def service(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield StoriesService(
            StoryRepository(session), clock=lambda: datetime(2026, 10, 11, tzinfo=UTC)
        )
