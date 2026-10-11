from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backlog_service.domain import Story, StoryChange, StoryPage
from backlog_service.models import StoryRecord


class StoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def commit(self) -> None:
        try:
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise

    def add(self, story: Story) -> Story:
        record = StoryRecord(**story.model_dump())
        self.session.add(record)
        self.commit()
        return Story.model_validate(record)

    def list_for_project(self, project_id: UUID, *, limit: int, offset: int) -> StoryPage:
        condition = StoryRecord.project_id == project_id
        total = self.session.scalar(select(func.count()).select_from(StoryRecord).where(condition))
        priority = case(
            (StoryRecord.priority == "high", 0), (StoryRecord.priority == "medium", 1), else_=2
        )
        records = self.session.scalars(
            select(StoryRecord)
            .where(condition)
            .order_by(priority, StoryRecord.created_at, StoryRecord.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return StoryPage(
            items=[Story.model_validate(r) for r in records],
            total=total or 0,
            limit=limit,
            offset=offset,
        )

    def record(self, project_id: UUID, story_id: UUID) -> StoryRecord | None:
        return self.session.scalar(
            select(StoryRecord).where(
                StoryRecord.project_id == project_id, StoryRecord.id == story_id
            )
        )

    def get_for_project(self, project_id: UUID, story_id: UUID) -> Story | None:
        record = self.record(project_id, story_id)
        return Story.model_validate(record) if record else None

    def update_for_project(
        self, project_id: UUID, story_id: UUID, change: StoryChange, now: datetime
    ) -> Story | None:
        record = self.record(project_id, story_id)
        if record is None:
            return None
        values = change.model_dump(exclude_unset=True)
        changed = False
        for name, value in values.items():
            if getattr(record, name) != value:
                setattr(record, name, value)
                changed = True
        if changed:
            record.updated_at = now
            self.commit()
        return Story.model_validate(record)
