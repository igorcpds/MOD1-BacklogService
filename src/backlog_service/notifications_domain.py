"""Project-scoped notification contracts; no HTTP, persistence or credentials."""

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

DeliveryState = Literal["pending", "sending", "delivered", "blocked", "failed", "uncertain"]


@dataclass(frozen=True)
class Claim:
    event_id: str
    token: UUID
    payload: dict[str, Any]
    attempt: int


@dataclass(frozen=True)
class Outcome:
    status: DeliveryState
    error: str | None = None
    http_status: int | None = None


def build_notification(
    event_id: UUID, project_id: UUID, action: str, changes: dict[str, Any], source: str
) -> dict[str, Any] | None:
    if action == "create":
        kind, title, priority = "backlog.item.created", "Item criado no backlog", "medium"
        body = "Um novo item foi criado no backlog do projeto."
    elif action == "update" and isinstance(changes.get("diff"), dict):
        diff = changes["diff"]
        relevant = [key for key in ("status", "is_blocked", "assignee_id") if key in diff]
        if not relevant:
            return None
        kind, title, priority = "backlog.item.updated", "Item do backlog atualizado", "medium"
        parts = []
        if "status" in diff:
            kind = "backlog.item.status_changed"
            labels = {
                "todo": "A fazer",
                "in_progress": "Em andamento",
                "review": "Em revisão",
                "done": "Concluído",
            }
            status = diff["status"].get("after")
            parts.append("Status: " + labels.get(status, "atualizado") + ".")
        if "is_blocked" in diff:
            blocked = diff["is_blocked"].get("after") is True
            kind = "backlog.item.blocked" if blocked else "backlog.item.unblocked"
            priority = "high" if blocked else "medium"
            parts.append("Item bloqueado." if blocked else "Bloqueio removido.")
        if "assignee_id" in diff:
            if len(relevant) == 1:
                kind = "backlog.item.assignee_changed"
            parts.append("Responsável atualizado.")
        body = " ".join(parts)
    else:
        return None
    # Only the item identifier is exported; descriptions, names and reasons may be private.
    if changes.get("item_id"):
        body += " Item: " + str(UUID(str(changes["item_id"]))) + "."

    return {
        "event_id": "mod1:backlog:" + str(event_id),
        "scope": "project",
        "project_id": str(project_id),
        "source": source,
        "type": kind,
        "title": title,
        "body": body,
        "priority": priority,
        "link": None,
    }
