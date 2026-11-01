from uuid import uuid4

import pytest
from pydantic import ValidationError
from story_context import context_for

from backlog_service.domain import Conflict, ItemChange, ItemDraft, Reorder


def test_expanded_item_preserves_legacy_and_guided_fields(service, project_id):
    ctx = context_for(project_id)
    epic = service.create_item(ctx, ItemDraft(title="Epic", kind="epic"))
    story = service.create_item(
        ctx,
        ItemDraft(
            title="Story",
            epic_id=epic.id,
            persona="PO",
            action="prioritize",
            benefit="deliver",
            guided=True,
            moscow_priority="must",
            estimate_value="1.25",
            estimate_unit="hours",
        ),
    )
    assert story.kind == "story" and story.version == 1
    assert story.epic_id == epic.id and story.estimate_value == "1.25"
    assert service.list(ctx).total == 1
    assert service.items(ctx).total == 2
    changed = service.update_item(
        ctx,
        story.id,
        ItemChange(is_blocked=True, blocked_reason="External dependency", expected_version=1),
    )
    assert changed.is_blocked and changed.status == "todo" and changed.version == 2
    history = service.history(ctx, story.id)
    assert history["total"] == 2
    assert history["items"][0]["actor_id"] == str(ctx.actor_id)
    with pytest.raises(Conflict):
        service.update_item(ctx, story.id, ItemChange(title="Stale", expected_version=1))


@pytest.mark.parametrize(
    "fields",
    [
        {"guided": True},
        {"estimate_value": "-1", "estimate_unit": "hours"},
        {"estimate_value": "1"},
        {"is_blocked": True},
        {"estimate_value": "NaN", "estimate_unit": "points"},
    ],
)
def test_item_validation(fields):
    with pytest.raises(ValidationError):
        ItemDraft(title="Invalid", **fields)


def test_dependency_dag_and_scope(service, project_id):
    ctx = context_for(project_id)
    a, b, c = [service.create_item(ctx, ItemDraft(title=x)) for x in "ABC"]
    service.add_dependency(ctx, a.id, b.id)
    service.add_dependency(ctx, b.id, c.id)
    for source, target in [(c.id, a.id), (a.id, a.id)]:
        with pytest.raises(Conflict):
            service.add_dependency(ctx, source, target)
    outsider = service.create_item(context_for(uuid4()), ItemDraft(title="Other"))
    with pytest.raises(Conflict):
        service.add_dependency(ctx, a.id, outsider.id)
    assert service.dependencies(ctx, a.id) == [{"depends_on_id": str(b.id), "status": "todo"}]
    service.remove_dependency(ctx, a.id, b.id)
    assert service.dependencies(ctx, a.id) == []


def test_canonical_reorder_and_content_history(service, project_id):
    from backlog_service.domain import ProjectContext

    old = context_for(project_id)
    ctx = ProjectContext(project_id, old.actor_id, old.permissions | {"backlog:reorder"})
    a, b = [service.create_item(ctx, ItemDraft(title=x)) for x in "AB"]
    board = service.board(ctx)
    version = board["version"]
    with pytest.raises(Conflict):
        service.reorder(ctx, Reorder(item_ids=[a.id], expected_version=version))
    result = service.reorder(ctx, Reorder(item_ids=[b.id, a.id], expected_version=version))
    assert [item.id for item in result["items"]] == [b.id, a.id]
    with pytest.raises(Conflict):
        service.reorder(ctx, Reorder(item_ids=[a.id, b.id], expected_version=version))
    assert service.content_summary(ctx)["total"] >= 4


def test_status_only_preserves_unavailable_assignee_and_reports_availability(service, project_id):
    from backlog_service.domain import ProjectContext

    class EligibilityControl:
        active = True
        checks = 0

        def acquire(self, project):
            return uuid4()

        def release(self, project, lease):
            pass

        def eligible(self, project, user):
            self.checks += 1
            return self.active

        def availability(self, project, user):
            return self.active

    control = EligibilityControl()
    service.control = control
    ctx = context_for(project_id)
    assignee = uuid4()
    item = service.create_item(ctx, ItemDraft(title="Keep attribution", assignee_id=assignee))
    assert control.checks == 1
    control.active = False
    developer = ProjectContext(
        project_id, ctx.actor_id, frozenset({"backlog:read", "backlog:update_status"})
    )
    updated = service.update_item(developer, item.id, ItemChange(status="done", expected_version=1))
    assert updated.status == "done" and updated.assignee_id == assignee
    assert updated.assignee_available is False
    assert control.checks == 1
    assert service.get_item(ctx, item.id).assignee_available is False
    assert service.items(ctx).items[0].assignee_available is False
    assert service.board(ctx)["columns"]["done"][0].assignee_available is False
    with pytest.raises(Conflict):
        service.update_item(ctx, item.id, ItemChange(assignee_id=uuid4(), expected_version=2))
