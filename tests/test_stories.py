from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import Session
from story_context import context_for

from backlog_service.database import create_database_engine
from backlog_service.domain import (
    InsufficientProjectPermissions,
    ProjectContext,
    StoryChange,
    StoryDraft,
)
from backlog_service.repository import StoryRepository
from backlog_service.service import StoriesService


@pytest.mark.parametrize(
    "padding", ["\ufeff", "\ufeff\u0085", "\u001c\ufeff\u001f", "\u00a0\ufeff \u2028"]
)
def test_title_normalization_matches_browser_unicode(service, project_id, actor_id, padding):
    story = service.create(
        context_for(project_id, actor_id), StoryDraft(title=padding + "História" + padding)
    )
    assert story.title == "História"
    assert service.list(context_for(project_id)).items[0].title == "História"


@pytest.mark.parametrize(
    "title", ["\ufeff", "\ufeff\u0085", "\u001c\ufeff\u001f", "\u00a0\ufeff \u2028"]
)
def test_title_cannot_contain_only_unicode_padding(title):
    with pytest.raises(ValidationError):
        StoryDraft(title=title)


def test_create_defaults_and_server_fields(service, project_id, actor_id):
    story = service.create(context_for(project_id, actor_id), StoryDraft(title="  História  "))
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
        context_for(project_id, actor_id),
        StoryDraft(
            title="🚀" * 120,
            description="<script>literal</script>\nsegunda linha",
            acceptance_criteria="🚀" * 2000,
        ),
    )
    saved = service.get(context_for(project_id), story.id)
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
        {"id": str(uuid4())},
        {"created_at": "2026-01-01"},
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
        service.create(
            context_for(project_id, actor_id), StoryDraft(title=title, priority=priority)
        )
    service.create(context_for(other, actor_id), StoryDraft(title="Alheia", priority="high"))
    first = service.list(context_for(project_id), limit=2)
    assert [s.title for s in first.items] == ["Alta", "Média"]
    assert (first.total, first.limit, first.offset) == (3, 2, 0)
    assert [s.title for s in service.list(context_for(project_id), limit=2, offset=2).items] == [
        "Baixa"
    ]
    assert service.list(context_for(project_id), offset=99).items == []
    assert service.get(context_for(other), first.items[0].id) is None
    assert service.update(context_for(other), first.items[0].id, StoryChange(status="done")) is None


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (20, -1)])
def test_invalid_pagination(service, project_id, limit, offset):
    with pytest.raises(ValueError):
        service.list(context_for(project_id), limit=limit, offset=offset)


def test_update_same_values_preserves_timestamp(service, project_id, actor_id):
    story = service.create(context_for(project_id, actor_id), StoryDraft(title="História"))
    service.clock = lambda: datetime(2026, 10, 12, tzinfo=UTC)
    assert service.update(context_for(project_id), story.id, StoryChange(status="todo")) == story


def test_update_changes_timestamp_and_reopens(service, project_id, actor_id):
    story = service.create(context_for(project_id, actor_id), StoryDraft(title="História"))
    later = datetime(2026, 10, 12, tzinfo=UTC)
    service.clock = lambda: later
    updated = service.update(
        context_for(project_id), story.id, StoryChange(priority="high", status="done")
    )
    assert (updated.priority, updated.status, updated.updated_at) == ("high", "done", later)
    reopened = service.update(context_for(project_id), story.id, StoryChange(status="todo"))
    assert (reopened.priority, reopened.status, reopened.created_at) == (
        "high",
        "todo",
        story.created_at,
    )


def test_persistence_after_reopen_engine(settings, service, project_id, actor_id):
    story = service.create(context_for(project_id, actor_id), StoryDraft(title="Persistente"))
    second = create_database_engine(settings)
    try:
        with Session(second) as session:
            assert (
                StoriesService(StoryRepository(session)).get(context_for(project_id), story.id)
                == story
            )
    finally:
        second.dispose()


@pytest.mark.parametrize("operation", ["create", "list", "get", "status", "text", "mixed"])
def test_application_denies_action_before_any_story_sql(
    engine, service, project_id, actor_id, operation
):
    context = ProjectContext(project_id, actor_id, frozenset())
    statements = []

    def record(connection, cursor, statement, parameters, execution_context, many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with pytest.raises(InsufficientProjectPermissions):
            if operation == "create":
                service.create(context, StoryDraft(title="Forbidden"))
            elif operation == "list":
                service.list(context)
            elif operation == "get":
                service.get(context, uuid4())
            else:
                changes = {
                    "status": StoryChange(status="done"),
                    "text": StoryChange(title="Forbidden"),
                    "mixed": StoryChange(status="done", description="Forbidden"),
                }
                service.update(context, uuid4(), changes[operation])
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert statements == []


def test_application_developer_can_update_only_status(service, project_id, actor_id):
    owner = context_for(project_id, actor_id)
    story = service.create(owner, StoryDraft(title="Original"))
    developer = ProjectContext(
        project_id, actor_id, frozenset({"backlog:read", "backlog:update_status"})
    )
    updated = service.update(developer, story.id, StoryChange(status="done"))
    assert service.get(developer, story.id) == updated
    assert updated.status == "done"
    assert updated.title == "Original"
    with pytest.raises(InsufficientProjectPermissions):
        service.update(developer, story.id, StoryChange(status="todo", title="Forbidden"))
    assert service.get(owner, story.id) == updated
