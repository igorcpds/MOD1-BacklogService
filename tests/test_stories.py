from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backlog_service.database import create_database_engine
from backlog_service.domain import StoryChange, StoryDraft
from backlog_service.repository import StoryRepository
from backlog_service.service import StoriesService


def test_create_defaults_and_server_fields(service, project_id, actor_id):
    story = service.create(project_id, actor_id, StoryDraft(title="  História  "))
    assert (story.title, story.priority, story.status) == ("História", "medium", "todo")
    assert (story.project_id, story.created_by) == (project_id, actor_id)
    assert story.created_at == story.updated_at == datetime(2026, 10, 11, tzinfo=UTC)
    assert story.id.version == 4
    assert (story.description, story.acceptance_criteria) == ("", "")


@pytest.mark.parametrize("value", ["", " \t\n ", "🚀" * 121, None, 4, True])
def test_invalid_title_rejected(value):
    with pytest.raises(ValidationError):
        StoryDraft(title=value)


def test_unicode_and_multiline_text_preserved(service, project_id, actor_id):
    story = service.create(
        project_id,
        actor_id,
        StoryDraft(
            title="🚀" * 120,
            description="<script>literal</script>\nsegunda linha",
            acceptance_criteria="🚀" * 2000,
        ),
    )
    saved = service.get(project_id, story.id)
    assert saved == story
    assert saved.description == "<script>literal</script>\nsegunda linha"


@pytest.mark.parametrize("field", ["description", "acceptance_criteria"])
@pytest.mark.parametrize("value", ["🚀" * 2001, None, 12])
def test_optional_text_limits(field, value):
    with pytest.raises(ValidationError):
        StoryDraft(title="História", **{field: value})


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"priority": None},
        {"status": None},
        {"priority": "urgent"},
        {"status": "closed"},
        {"title": "novo"},
        {"created_by": str(uuid4())},
        {"project_id": str(uuid4())},
        {"updated_at": "2026-01-01"},
        {"status": 1},
    ],
)
def test_patch_rejects_empty_null_and_immutable_fields(data):
    with pytest.raises(ValidationError):
        StoryChange(**data)


def test_priority_pagination_and_project_isolation(service, project_id, actor_id):
    other = uuid4()
    for title, priority in [("Baixa", "low"), ("Alta", "high"), ("Média", "medium")]:
        service.create(project_id, actor_id, StoryDraft(title=title, priority=priority))
    service.create(other, actor_id, StoryDraft(title="Alheia", priority="high"))
    first = service.list(project_id, limit=2)
    assert [s.title for s in first.items] == ["Alta", "Média"]
    assert (first.total, first.limit, first.offset) == (3, 2, 0)
    assert [s.title for s in service.list(project_id, limit=2, offset=2).items] == ["Baixa"]
    assert service.list(project_id, offset=99).items == []
    assert service.get(other, first.items[0].id) is None
    assert service.update(other, first.items[0].id, StoryChange(status="done")) is None


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (20, -1)])
def test_invalid_pagination(service, project_id, limit, offset):
    with pytest.raises(ValueError):
        service.list(project_id, limit=limit, offset=offset)


def test_update_same_values_preserves_timestamp(service, project_id, actor_id):
    story = service.create(project_id, actor_id, StoryDraft(title="História"))
    service.clock = lambda: datetime(2026, 10, 12, tzinfo=UTC)
    assert service.update(project_id, story.id, StoryChange(status="todo")) == story


def test_update_changes_timestamp_and_reopens(service, project_id, actor_id):
    story = service.create(project_id, actor_id, StoryDraft(title="História"))
    later = datetime(2026, 10, 12, tzinfo=UTC)
    service.clock = lambda: later
    updated = service.update(project_id, story.id, StoryChange(priority="high", status="done"))
    assert (updated.priority, updated.status, updated.updated_at) == ("high", "done", later)
    reopened = service.update(project_id, story.id, StoryChange(status="todo"))
    assert (reopened.priority, reopened.status, reopened.created_at) == (
        "high",
        "todo",
        story.created_at,
    )


def test_persistence_after_reopen_engine(settings, service, project_id, actor_id):
    story = service.create(project_id, actor_id, StoryDraft(title="Persistente"))
    second = create_database_engine(settings)
    try:
        with Session(second) as session:
            assert StoriesService(StoryRepository(session)).get(project_id, story.id) == story
    finally:
        second.dispose()
