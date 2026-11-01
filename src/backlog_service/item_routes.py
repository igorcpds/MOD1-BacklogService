"""HTTP adapters for expanded backlog; rules remain in application/domain."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict

from backlog_service.dependencies import Context, Service
from backlog_service.domain import (
    Item,
    ItemChange,
    ItemDraft,
    ItemPage,
    Kind,
    MoSCoW,
    Priority,
    Reorder,
    SearchText,
    Status,
)

router = APIRouter(prefix="/projects/{project_id}")


class EpicDraft(ItemDraft):
    kind: Literal["epic"] = "epic"


class TaskDraft(ItemDraft):
    kind: Literal["task"] = "task"


class DependencyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    depends_on_id: UUID


@router.get("/items", response_model=ItemPage)
def list_items(
    context: Context,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[SearchText, Query()] = "",
    status: Status | None = None,
    priority: Priority | None = None,
    moscow_priority: MoSCoW | None = None,
    kind: Kind | None = None,
    epic_id: UUID | None = None,
    assignee_id: UUID | None = None,
    blocked: bool | None = None,
) -> ItemPage:
    return service.items(
        context,
        limit=limit,
        offset=offset,
        q=q,
        status=status,
        priority=priority,
        moscow_priority=moscow_priority,
        kind=kind,
        epic_id=epic_id,
        assignee_id=assignee_id,
        is_blocked=blocked,
    )


@router.post("/items", response_model=Item, status_code=201)
def create_item(draft: ItemDraft, context: Context, service: Service) -> Item:
    return service.create_item(context, draft)


@router.post("/items/reorder")
def reorder(draft: Reorder, context: Context, service: Service) -> dict[str, Any]:
    return service.reorder(context, draft)


@router.get("/items/{item_id}", response_model=Item)
def get_item(item_id: UUID, context: Context, service: Service) -> Item:
    return service.get_item(context, item_id)


@router.patch("/items/{item_id}", response_model=Item)
def update_item(item_id: UUID, change: ItemChange, context: Context, service: Service) -> Item:
    return service.update_item(context, item_id, change)


@router.get("/epics", response_model=ItemPage)
def list_epics(
    context: Context,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ItemPage:
    return service.items(context, limit=limit, offset=offset, kind="epic")


@router.post("/epics", response_model=Item, status_code=201)
def create_epic(draft: EpicDraft, context: Context, service: Service) -> Item:
    return service.create_item(context, draft)


@router.get("/tasks", response_model=ItemPage)
def list_tasks(
    context: Context,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ItemPage:
    return service.items(context, limit=limit, offset=offset, kind="task")


@router.post("/tasks", response_model=Item, status_code=201)
def create_task(draft: TaskDraft, context: Context, service: Service) -> Item:
    return service.create_item(context, draft)


@router.get("/items/{item_id}/history")
def history(
    item_id: UUID,
    context: Context,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return service.history(context, item_id, limit, offset)


@router.get("/items/{item_id}/dependencies")
def dependencies(item_id: UUID, context: Context, service: Service) -> list[dict[str, str]]:
    return service.dependencies(context, item_id)


@router.post("/items/{item_id}/dependencies", status_code=201)
def add_dependency(
    item_id: UUID, draft: DependencyDraft, context: Context, service: Service
) -> dict[str, str]:
    service.add_dependency(context, item_id, draft.depends_on_id)
    return {"depends_on_id": str(draft.depends_on_id)}


@router.delete("/items/{item_id}/dependencies/{target}", status_code=204)
def remove_dependency(item_id: UUID, target: UUID, context: Context, service: Service) -> Response:
    service.remove_dependency(context, item_id, target)
    return Response(status_code=204)


@router.get("/board")
def board(context: Context, service: Service) -> dict[str, Any]:
    return service.board(context)


@router.get("/content-summary")
def content_summary(context: Context, service: Service) -> dict[str, Any]:
    return service.content_summary(context)
