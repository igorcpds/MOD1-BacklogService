from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backlog_service.domain import Story, StoryChange, StoryDraft, StoryPage
from backlog_service.repository import StoryRepository


def utc_now() -> datetime:
    return datetime.now(UTC)


class StoriesService:
    def __init__(
        self,
        repository: StoryRepository,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.repository, self.clock, self.id_factory = repository, clock, id_factory

    def create(self, project_id: UUID, actor_id: UUID, draft: StoryDraft) -> Story:
        now = self.clock()
        return self.repository.add(
            Story(
                id=self.id_factory(),
                project_id=project_id,
                created_by=actor_id,
                title=draft.title,
                description=draft.description,
                acceptance_criteria=draft.acceptance_criteria,
                priority=draft.priority,
                status="todo",
                created_at=now,
                updated_at=now,
            )
        )

    def list(self, project_id: UUID, *, limit: int = 20, offset: int = 0) -> StoryPage:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        return self.repository.list_for_project(project_id, limit=limit, offset=offset)

    def get(self, project_id: UUID, story_id: UUID) -> Story | None:
        return self.repository.get_for_project(project_id, story_id)

    def update(self, project_id: UUID, story_id: UUID, change: StoryChange) -> Story | None:
        return self.repository.update_for_project(project_id, story_id, change, self.clock())
