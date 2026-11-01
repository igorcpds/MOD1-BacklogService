"""Local proposed review-event application; no external event semantics are assumed."""

import hashlib
from datetime import timedelta
from typing import Any

from backlog_service.domain import (
    Conflict,
    DependencyUnavailable,
    InsufficientProjectPermissions,
    ProjectContext,
    ReviewEvent,
    ReviewPrincipal,
    Status,
)
from backlog_service.item_service import ItemsService


class ReviewService:
    def __init__(
        self, items: ItemsService, mapping: dict[str, Status], principal: ReviewPrincipal
    ) -> None:
        self.items, self.mapping, self.principal = items, mapping, principal
        self.repository = items.repository

    def apply(self, context: ProjectContext, event: ReviewEvent) -> dict[str, Any]:
        context.require("backlog:update_status")
        if (
            context.project_id not in self.principal.project_ids
            or event.project_id != context.project_id
        ):
            raise InsufficientProjectPermissions("Insufficient project permissions")
        status = self.mapping.get(event.event_type)
        if status is None:
            raise DependencyUnavailable("Code review event mapping is not configured")
        if status not in {"todo", "in_progress", "done"}:
            raise DependencyUnavailable("Code review event mapping is not configured")
        if event.occurred_at > self.items.clock() + timedelta(minutes=5):
            raise Conflict("Event timestamp is in the future")
        body_hash = hashlib.sha256(event.model_dump_json().encode()).hexdigest()
        with self.items.mutation(context, "backlog:update_status") as mutation:
            existing = self.repository.review_event(context.project_id, event.event_id)
            if existing is not None:
                if existing["body_hash"] != body_hash:
                    raise Conflict("Event ID was already used with different content")
                result: dict[str, Any] = existing["result"]
                mutation.changed = False
                return result
            item = self.repository.item(context.project_id, event.item_id)
            last = self.repository.last_review_time(context.project_id, item.id)
            if last is not None and event.occurred_at <= last:
                raise Conflict("Event order conflict")
            if item.version != event.expected_item_version:
                raise Conflict("Item version conflict")
            now = self.items.clock()
            changed = item.model_copy(
                update={"status": status, "version": item.version + 1, "updated_at": now}
            )
            self.repository.save_item(
                changed,
                context.actor_id,
                now,
                action="code_review",
                diff={
                    "status": {"before": item.status, "after": status},
                    "integration": {
                        "principal": self.principal.name,
                        "event_id": str(event.event_id),
                        "event_type": event.event_type,
                    },
                },
            )
            result = {
                "event_id": str(event.event_id),
                "project_id": str(context.project_id),
                "item_id": str(item.id),
                "item_version": changed.version,
                "status": status,
                "applied_at": now.isoformat(),
            }
            self.repository.save_review_event(
                event, self.principal.name, context.actor_id, body_hash, result, now
            )
        return result
