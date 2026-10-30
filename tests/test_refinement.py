from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backlog_service.domain import StoryChange, StoryDraft


def test_text_patch_persists_and_preserves_immutable_fields(service, project_id, actor_id):
    story = service.create(project_id, actor_id, StoryDraft(title="Original"))
    later = datetime(2026, 10, 12, tzinfo=UTC)
    service.clock = lambda: later
    updated = service.update(
        project_id,
        story.id,
        StoryChange(
            title="\ufeff Nova história \u00a0",
            description="<b>literal</b>\nTexto",
            acceptance_criteria="🚀" * 2000,
            priority="high",
            status="done",
        ),
    )
    assert updated.title == "Nova história"
    assert updated.description == "<b>literal</b>\nTexto"
    assert updated.acceptance_criteria == "🚀" * 2000
    assert updated.updated_at == later
    assert (updated.id, updated.created_by, updated.project_id, updated.created_at) == (
        story.id,
        actor_id,
        project_id,
        story.created_at,
    )
    assert service.get(project_id, story.id) == updated
    assert service.update(uuid4(), story.id, StoryChange(title="Alheia")) is None
    service.clock = lambda: datetime(2026, 10, 13, tzinfo=UTC)
    assert service.update(project_id, story.id, StoryChange(title=" Nova história ")) == updated
    cleared = service.update(
        project_id, story.id, StoryChange(description="", acceptance_criteria="")
    )
    assert (cleared.description, cleared.acceptance_criteria) == ("", "")


@pytest.mark.parametrize(
    "data",
    [
        {"title": ""},
        {"title": "\ufeff \n"},
        {"title": "🚀" * 121},
        {"title": None},
        {"title": 3},
        {"description": None},
        {"description": 1},
        {"description": "x" * 2001},
        {"acceptance_criteria": "x" * 2001},
        {"acceptance_criteria": None},
        {"status": "done", "description": None},
    ],
)
def test_text_patch_rejects_invalid_values(data):
    with pytest.raises(ValidationError):
        StoryChange(**data)


@pytest.mark.parametrize(
    "query,expected",
    [
        ("  ENTREGA  ", ["Entrega alta", "Entrega média", "Entrega baixa"]),
        ("árvore", ["Entrega alta"]),
        ("100%", ["Entrega alta"]),
        ("a_b", ["Entrega média"]),
        ("!", ["Entrega baixa"]),
        ("missing", []),
        ("' OR 1=1 --", []),
    ],
)
def test_literal_case_insensitive_search(service, project_id, actor_id, query, expected):
    for title, description, priority in [
        ("Entrega alta", "ÁRVORE 100%", "high"),
        ("Entrega média", "100x a_b", "medium"),
        ("Entrega baixa", "axb!", "low"),
    ]:
        service.create(
            project_id,
            actor_id,
            StoryDraft(title=title, description=description, priority=priority),
        )
    service.create(uuid4(), actor_id, StoryDraft(title="Entrega alheia", priority="high"))
    page = service.list(project_id, q=query)
    assert [story.title for story in page.items] == expected
    assert page.total == len(expected)


def test_combined_filters_precede_count_and_pagination(service, project_id, actor_id):
    ids = []
    for index in range(4):
        story = service.create(
            project_id, actor_id, StoryDraft(title=f"Entrega {index}", priority="high")
        )
        ids.append(story.id)
        if index < 3:
            service.update(project_id, story.id, StoryChange(status="done"))
    service.create(project_id, actor_id, StoryDraft(title="Entrega média"))
    page = service.list(project_id, q="entrega", status="done", priority="high", limit=1, offset=1)
    assert (page.total, page.limit, page.offset) == (3, 1, 1)
    assert [story.id for story in page.items] == sorted(ids[:3])[1:2]
    exact = service.list(project_id, q=str(ids[0]).upper())
    assert [story.id for story in exact.items] == [ids[0]]
    assert service.list(project_id, q=str(ids[0])[:20]).total == 0
    assert service.list(project_id, q=str(ids[0]), status="todo").total == 0
