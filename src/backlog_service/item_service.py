"""Application use cases for items, graphs, board ordering and write coordination."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError

from backlog_service.domain import (
    Conflict,
    Item,
    ItemChange,
    ItemDraft,
    ItemPage,
    MissingItem,
    ProjectContext,
    Reorder,
)
from backlog_service.item_repository import ItemRepository


def utc_now() -> datetime:
    return datetime.now(UTC)


class WriteControl(Protocol):
    def acquire(self, project_id: UUID) -> UUID: ...
    def release(self, project_id: UUID, lease_id: UUID) -> None: ...
    def eligible(self, project_id: UUID, user_id: UUID) -> bool: ...
    def availability(self, project_id: UUID, user_id: UUID) -> bool | None: ...


@dataclass
class MutationState:
    version: int
    changed: bool = True


class ItemsService:
    def __init__(
        self,
        repository: ItemRepository,
        *,
        clock: Callable[[], datetime] = utc_now,
        control: WriteControl | None = None,
    ) -> None:
        self.repository, self.clock, self.control = repository, clock, control

    @contextmanager
    def mutation(self, context: ProjectContext, permission: str) -> Iterator[MutationState]:
        context.require(permission)
        if context.archived or context.project_status not in {"active", "planned"}:
            raise Conflict("Project is read only")
        lease = self.control.acquire(context.project_id) if self.control else None
        try:
            state = MutationState(self.repository.lock(context.project_id))
            yield state
            if state.changed:
                self.repository.advance(context.project_id)
                self.repository.commit()
            else:
                self.repository.rollback()
        except BaseException:
            self.repository.rollback()
            raise
        finally:
            if lease is not None and self.control is not None:
                self.control.release(context.project_id, lease)

    def validate_references(
        self,
        context: ProjectContext,
        draft: ItemDraft,
        item_id: UUID | None = None,
        *,
        validate_assignee: bool = True,
    ) -> None:
        for identifier, kind in [(draft.epic_id, "epic"), (draft.parent_story_id, "story")]:
            if identifier:
                try:
                    parent = self.repository.item(context.project_id, identifier)
                except MissingItem:
                    raise Conflict("Parent unavailable") from None
                if identifier == item_id or parent.kind != kind:
                    raise Conflict("Invalid parent")
        if (
            validate_assignee
            and draft.assignee_id is not None
            and self.control is not None
            and not self.control.eligible(context.project_id, draft.assignee_id)
        ):
            raise Conflict("Assignee unavailable")

    def create_item(self, context: ProjectContext, draft: ItemDraft) -> Item:
        with self.mutation(context, "backlog:create"):
            self.validate_references(context, draft)
            now = self.clock()
            item = Item(
                id=uuid4(),
                project_id=context.project_id,
                created_by=context.actor_id,
                created_at=now,
                updated_at=now,
                status="todo",
                position=len(self.repository.all_items(context.project_id)),
                **draft.model_dump(),
            )
            self.repository.save_item(
                item,
                context.actor_id,
                now,
                new=True,
                diff={
                    k: {"before": None, "after": v}
                    for k, v in draft.model_dump(mode="json").items()
                },
            )
        return self.present_item(context, item)

    def update_item(self, context: ProjectContext, item_id: UUID, change: ItemChange) -> Item:
        values = change.model_dump(exclude_unset=True, exclude={"expected_version"})
        permission = "backlog:update_status" if set(values) == {"status"} else "backlog:update"
        with self.mutation(context, permission):
            item = self.repository.item(context.project_id, item_id)
            if change.expected_version is not None and change.expected_version != item.version:
                raise Conflict("Item version conflict")
            merged = item.model_dump(include=set(ItemDraft.model_fields)) | {
                k: v for k, v in values.items() if k != "status"
            }
            try:
                draft = ItemDraft.model_validate(merged)
            except ValidationError:
                raise Conflict("Invalid item state") from None
            self.validate_references(
                context,
                draft,
                item_id,
                validate_assignee="assignee_id" in values
                and values["assignee_id"] != item.assignee_id,
            )
            diff = {
                key: {"before": getattr(item, key), "after": value}
                for key, value in values.items()
                if getattr(item, key) != value
            }
            if diff:
                now = self.clock()
                item = item.model_copy(
                    update=values | {"version": item.version + 1, "updated_at": now}
                )
                self.repository.save_item(item, context.actor_id, now, diff=diff)
        return self.present_item(context, item)

    def items(
        self, context: ProjectContext, *, limit: int = 20, offset: int = 0, **filters: Any
    ) -> ItemPage:
        context.require("backlog:read")
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        page = self.repository.page(context.project_id, limit=limit, offset=offset, **filters)
        return page.model_copy(update={"items": self.present_items(context, page.items)})

    def get_item(self, context: ProjectContext, item_id: UUID) -> Item:
        context.require("backlog:read")
        return self.present_item(context, self.repository.item(context.project_id, item_id))

    def history(
        self, context: ProjectContext, item_id: UUID, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        context.require("backlog:read")
        return self.repository.history(context.project_id, item_id, limit, offset)

    def dependencies(self, context: ProjectContext, item_id: UUID) -> list[dict[str, str]]:
        self.get_item(context, item_id)
        return [
            {
                "depends_on_id": str(target),
                "status": self.repository.item(context.project_id, target).status,
            }
            for source, target in self.repository.graph(context.project_id)
            if source == item_id
        ]

    def add_dependency(self, context: ProjectContext, item_id: UUID, target: UUID) -> None:
        self.change_dependency(context, item_id, target, remove=False)

    def remove_dependency(self, context: ProjectContext, item_id: UUID, target: UUID) -> None:
        self.change_dependency(context, item_id, target, remove=True)

    def change_dependency(
        self, context: ProjectContext, item_id: UUID, target: UUID, *, remove: bool
    ) -> None:
        with self.mutation(context, "backlog:update"):
            item = self.repository.item(context.project_id, item_id)
            try:
                self.repository.item(context.project_id, target)
            except MissingItem:
                raise Conflict("Dependency unavailable") from None
            graph = self.repository.graph(context.project_id)
            if not remove:
                visited: set[UUID] = set()
                pending = [target]
                while pending:
                    current = pending.pop()
                    if current == item_id:
                        raise Conflict("Dependency cycle")
                    if current not in visited:
                        visited.add(current)
                        pending.extend(b for a, b in graph if a == current)
            exists = (item_id, target) in graph
            if exists != (not remove):
                self.repository.dependency(context.project_id, item_id, target, remove=remove)
                now = self.clock()
                item = item.model_copy(update={"version": item.version + 1, "updated_at": now})
                self.repository.save_item(
                    item,
                    context.actor_id,
                    now,
                    action="dependency_remove" if remove else "dependency_add",
                    diff={
                        "depends_on_id": {
                            "before": str(target) if remove else None,
                            "after": None if remove else str(target),
                        }
                    },
                )

    def board(self, context: ProjectContext) -> dict[str, Any]:
        context.require("backlog:read")
        version = self.repository.version(context.project_id)
        items = self.repository.all_items(context.project_id)
        if len(items) > 5000:
            raise Conflict("Board limited to 5000 items; use item filters")
        graph = self.repository.graph(context.project_id)
        if version != self.repository.version(context.project_id):
            raise Conflict("Board changed during read; refresh the board")
        by_id = {item.id: item for item in items}
        unresolved: dict[str, list[str]] = {str(item.id): [] for item in items}
        for source, target in graph:
            if source not in by_id or target not in by_id:
                raise Conflict("Board references unavailable item")
            if by_id[target].status != "done":
                unresolved[str(source)].append(str(target))
        items = self.present_items(context, items)
        return {
            "version": version,
            "columns": {
                status: [item for item in items if item.status == status]
                for status in ("todo", "in_progress", "done")
            },
            "unresolved_dependencies": unresolved,
        }

    def reorder(self, context: ProjectContext, draft: Reorder) -> dict[str, Any]:
        with self.mutation(context, "backlog:reorder") as order:
            if order.version != draft.expected_version:
                raise Conflict("Board version conflict")
            items = self.repository.all_items(context.project_id)
            filters = draft.group.model_dump(exclude_unset=True) if draft.group else {}
            group = [
                item
                for item in items
                if all(getattr(item, key) == value for key, value in filters.items())
            ]
            if len(set(draft.item_ids)) != len(draft.item_ids) or set(draft.item_ids) != {
                i.id for i in group
            }:
                raise Conflict("Reorder requires the complete canonical group")
            positions = sorted(i.position for i in group)
            mapping = {item.id: item for item in group}
            now = self.clock()
            result = []
            for identifier, position in zip(draft.item_ids, positions, strict=True):
                previous = mapping[identifier]
                item = previous.model_copy(
                    update={
                        "position": position,
                        "version": previous.version + 1,
                        "updated_at": now,
                    }
                )
                self.repository.save_item(
                    item,
                    context.actor_id,
                    now,
                    action="reorder",
                    diff={"position": {"before": previous.position, "after": position}},
                )
                result.append(item)
            version = order.version + 1
        return {"version": version, "items": self.present_items(context, result)}

    def present_item(self, context: ProjectContext, item: Item) -> Item:
        return self.present_items(context, [item])[0]

    def present_items(self, context: ProjectContext, items: list[Item]) -> list[Item]:
        availability: dict[UUID, bool | None] = {}
        result: list[Item] = []
        for item in items:
            if item.assignee_id is not None and self.control is not None:
                if item.assignee_id not in availability:
                    availability[item.assignee_id] = self.control.availability(
                        context.project_id, item.assignee_id
                    )
                item = item.model_copy(
                    update={"assignee_available": availability[item.assignee_id]}
                )
            result.append(item)
        return result

    def content_summary(self, context: ProjectContext) -> dict[str, Any]:
        context.require("backlog:read")
        return self.repository.content_summary(context.project_id)
