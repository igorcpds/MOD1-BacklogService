from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backlog_service.domain import (
    ItemChange,
    ItemDraft,
    Priority,
    ProjectContext,
    Status,
    Story,
    StoryChange,
    StoryDraft,
    StoryPage,
    trim_padding,
)
from backlog_service.item_repository import ItemRepository
from backlog_service.item_service import ItemsService, WriteControl
from backlog_service.repository import StoryRepository


def utc_now() -> datetime:
    return datetime.now(UTC)


class StoriesService(ItemsService):
    """Legacy stories contract backed by the same versioned item use cases."""

    def __init__(
        self,
        repository: StoryRepository,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
        control: WriteControl | None = None,
    ) -> None:
        super().__init__(ItemRepository.from_repository(repository), clock=clock, control=control)
        self.id_factory = id_factory

    def create(self, context: ProjectContext, draft: StoryDraft) -> Story:
        return Story.model_validate(
            self.create_item(context, ItemDraft(**draft.model_dump())).model_dump()
        )

    def list(
        self,
        context: ProjectContext,
        *,
        limit: int = 20,
        offset: int = 0,
        q: str = "",
        status: Status | None = None,
        priority: Priority | None = None,
    ) -> StoryPage:
        context.require("backlog:read")
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        query = str(trim_padding(q))
        if len(query) > 200:
            raise ValueError("Invalid search")
        return self.repository.list_for_project(
            context.project_id,
            limit=limit,
            offset=offset,
            q=query,
            status=status,
            priority=priority,
        )

    def get(self, context: ProjectContext, story_id: UUID) -> Story | None:
        context.require("backlog:read")
        return self.repository.get_for_project(context.project_id, story_id)

    def update(self, context: ProjectContext, story_id: UUID, change: StoryChange) -> Story | None:
        context.require(
            "backlog:update_status" if change.model_fields_set == {"status"} else "backlog:update"
        )
        if context.archived or context.project_status not in {"active", "planned"}:
            from backlog_service.domain import Conflict

            raise Conflict("Project is read only")
        story = self.repository.get_for_project(context.project_id, story_id)
        if story is None:
            return None
        return Story.model_validate(
            self.update_item(
                context, story_id, ItemChange(**change.model_dump(exclude_unset=True))
            ).model_dump()
        )
