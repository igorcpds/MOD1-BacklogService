"""Expanded item persistence; atomic project lock serializes graph/order changes."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backlog_service.domain import Item, ItemPage, MissingItem, Recommendation, ReviewEvent
from backlog_service.models import (
    DependencyRecord,
    HistoryRecord,
    ProjectOrderRecord,
    RecommendationEventRecord,
    RecommendationRecord,
    ReviewEventRecord,
    StoryRecord,
)
from backlog_service.repository import StoryRepository


class ItemRepository(StoryRepository):
    def lock(self, project_id: UUID) -> int:
        dialect = self.session.get_bind().dialect.name
        statement = (sqlite_insert if dialect == "sqlite" else pg_insert)(ProjectOrderRecord)
        self.session.execute(
            statement.values(project_id=project_id, version=0).on_conflict_do_nothing()
        )
        # SQLite ignores FOR UPDATE, so obtain its writer lock before inspecting state.
        self.session.execute(
            update(ProjectOrderRecord)
            .where(ProjectOrderRecord.project_id == project_id)
            .values(version=ProjectOrderRecord.version)
        )
        order = self.session.scalar(
            select(ProjectOrderRecord)
            .where(ProjectOrderRecord.project_id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert order is not None
        return order.version

    @classmethod
    def from_repository(cls, repository: StoryRepository) -> "ItemRepository":
        return cls(repository.session)

    def rollback(self) -> None:
        self.session.rollback()

    def advance(self, project_id: UUID) -> None:
        self.session.execute(
            update(ProjectOrderRecord)
            .where(ProjectOrderRecord.project_id == project_id)
            .values(version=ProjectOrderRecord.version + 1)
        )

    def version(self, project_id: UUID) -> int:
        return (
            self.session.scalar(
                select(ProjectOrderRecord.version).where(
                    ProjectOrderRecord.project_id == project_id
                )
            )
            or 0
        )

    def all_items(self, project_id: UUID) -> list[Item]:
        return [
            Item.model_validate(r)
            for r in self.session.scalars(
                select(StoryRecord)
                .where(StoryRecord.project_id == project_id)
                .order_by(StoryRecord.position, StoryRecord.created_at, StoryRecord.id)
            ).all()
        ]

    def item(self, project_id: UUID, item_id: UUID) -> Item:
        record = self.record(project_id, item_id)
        if record is None:
            raise MissingItem("Item unavailable")
        return Item.model_validate(record)

    def page(
        self, project_id: UUID, *, limit: int = 20, offset: int = 0, **filters: Any
    ) -> ItemPage:
        items = self.all_items(project_id)
        query = str(filters.pop("q", "")).strip().casefold()
        items = [
            i
            for i in items
            if (
                not query
                or query in i.title.casefold()
                or query in i.description.casefold()
                or query == str(i.id)
            )
            and all(value is None or getattr(i, key) == value for key, value in filters.items())
        ]
        return ItemPage(
            items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset
        )

    def audit(
        self, item: Item, actor_id: UUID, action: str, diff: dict[str, Any], now: datetime
    ) -> None:
        self.session.add(
            HistoryRecord(
                id=uuid4(),
                project_id=item.project_id,
                item_id=item.id,
                actor_id=actor_id,
                action=action,
                version=item.version,
                created_at=now,
                diff_json=json.dumps(diff, default=str, ensure_ascii=False),
            )
        )

    def save_item(
        self,
        item: Item,
        actor_id: UUID,
        now: datetime,
        *,
        new: bool = False,
        diff: dict[str, Any] | None = None,
        action: str = "update",
    ) -> Item:
        if new:
            record = StoryRecord(**item.model_dump(exclude={"assignee_available"}))
            self.session.add(record)
        else:
            existing = self.record(item.project_id, item.id)
            assert existing is not None
            record = existing
            for key, value in item.model_dump(exclude={"assignee_available"}).items():
                setattr(record, key, value)
        self.audit(item, actor_id, "create" if new else action, diff or {}, now)
        self.session.flush()
        return item

    def graph(self, project_id: UUID) -> list[tuple[UUID, UUID]]:
        return [
            (r.item_id, r.depends_on_id)
            for r in self.session.scalars(
                select(DependencyRecord).where(DependencyRecord.project_id == project_id)
            )
        ]

    def dependency(self, project_id: UUID, source: UUID, target: UUID, *, remove: bool) -> None:
        record = self.session.get(DependencyRecord, (project_id, source, target))
        if remove:
            if record:
                self.session.delete(record)
        elif record is None:
            self.session.add(
                DependencyRecord(project_id=project_id, item_id=source, depends_on_id=target)
            )

    def history(self, project_id: UUID, item_id: UUID, limit: int, offset: int) -> dict[str, Any]:
        self.item(project_id, item_id)
        condition = (HistoryRecord.project_id == project_id) & (HistoryRecord.item_id == item_id)
        total = (
            self.session.scalar(select(func.count()).select_from(HistoryRecord).where(condition))
            or 0
        )
        rows = self.session.scalars(
            select(HistoryRecord)
            .where(condition)
            .order_by(
                HistoryRecord.version.desc(), HistoryRecord.created_at.desc(), HistoryRecord.id
            )
            .limit(limit)
            .offset(offset)
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": str(r.id),
                    "item_id": str(r.item_id),
                    "actor_id": str(r.actor_id),
                    "action": r.action,
                    "version": r.version,
                    "created_at": r.created_at.isoformat(),
                    "diff": json.loads(r.diff_json),
                }
                for r in rows
            ],
        }

    def content_summary(self, project_id: UUID) -> dict[str, Any]:
        counts = {
            kind: count
            for kind, count in self.session.execute(
                select(StoryRecord.kind, func.count())
                .where(StoryRecord.project_id == project_id)
                .group_by(StoryRecord.kind)
            ).all()
        }
        history = (
            self.session.scalar(
                select(func.count())
                .select_from(HistoryRecord)
                .where(HistoryRecord.project_id == project_id)
            )
            or 0
        )
        recommendations = (
            self.session.scalar(
                select(func.count())
                .select_from(RecommendationRecord)
                .where(RecommendationRecord.project_id == project_id)
            )
            or 0
        )
        recommendation_events = (
            self.session.scalar(
                select(func.count())
                .select_from(RecommendationEventRecord)
                .where(RecommendationEventRecord.project_id == project_id)
            )
            or 0
        )
        review_events = (
            self.session.scalar(
                select(func.count())
                .select_from(ReviewEventRecord)
                .where(ReviewEventRecord.project_id == project_id)
            )
            or 0
        )
        return {
            "review_events": review_events,
            "recommendations": recommendations,
            "recommendation_events": recommendation_events,
            "project_id": str(project_id),
            "stories": counts.get("story", 0),
            "epics": counts.get("epic", 0),
            "tasks": counts.get("task", 0),
            "history": history,
            "total": sum(counts.values())
            + history
            + recommendations
            + recommendation_events
            + review_events,
        }

    def save_recommendation(
        self, recommendation: "Recommendation", actor: UUID, now: datetime
    ) -> None:
        record = self.session.get(RecommendationRecord, recommendation.id)
        if record is None:
            record = RecommendationRecord(
                id=recommendation.id,
                project_id=recommendation.project_id,
                created_by=recommendation.created_by,
                created_at=recommendation.created_at,
            )
            self.session.add(record)
        record.status = recommendation.status
        record.version = recommendation.version
        record.payload_json = recommendation.model_dump_json()
        self.session.add(
            RecommendationEventRecord(
                id=uuid4(),
                project_id=recommendation.project_id,
                recommendation_id=recommendation.id,
                actor_id=actor,
                status=recommendation.status,
                version=recommendation.version,
                created_at=now,
            )
        )
        self.session.flush()

    def get_recommendation(self, project_id: UUID, recommendation_id: UUID) -> "Recommendation":
        record = self.session.scalar(
            select(RecommendationRecord)
            .where(
                RecommendationRecord.project_id == project_id,
                RecommendationRecord.id == recommendation_id,
            )
            .execution_options(populate_existing=True)
        )
        if record is None:
            raise MissingItem("Recommendation unavailable")
        return Recommendation.model_validate_json(record.payload_json)

    def recommendations(self, project_id: UUID, limit: int, offset: int) -> dict[str, Any]:
        rows = self.session.scalars(
            select(RecommendationRecord)
            .where(RecommendationRecord.project_id == project_id)
            .order_by(RecommendationRecord.created_at.desc(), RecommendationRecord.id)
            .limit(limit)
            .offset(offset)
        )
        total = (
            self.session.scalar(
                select(func.count())
                .select_from(RecommendationRecord)
                .where(RecommendationRecord.project_id == project_id)
            )
            or 0
        )
        return {
            "items": [Recommendation.model_validate_json(row.payload_json) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def store_constraints(self, recommendation_id: UUID, constraints: dict[str, Any]) -> None:
        record = self.session.get(RecommendationRecord, recommendation_id)
        assert record is not None
        record.constraints_json = json.dumps(constraints, ensure_ascii=False)

    def recommendation_constraints(self, recommendation_id: UUID) -> dict[str, Any]:
        record = self.session.get(RecommendationRecord, recommendation_id)
        assert record is not None
        value: dict[str, Any] = json.loads(record.constraints_json)
        return value

    def review_event(self, project_id: UUID, event_id: UUID) -> dict[str, Any] | None:
        record = self.session.get(ReviewEventRecord, (project_id, event_id))
        if record is None:
            return None
        return {"body_hash": record.body_hash, "result": json.loads(record.result_json)}

    def last_review_time(self, project_id: UUID, item_id: UUID) -> datetime | None:
        value = self.session.scalar(
            select(func.max(ReviewEventRecord.occurred_at)).where(
                ReviewEventRecord.project_id == project_id, ReviewEventRecord.item_id == item_id
            )
        )
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value

    def save_review_event(
        self,
        event: "ReviewEvent",
        principal: str,
        actor_id: UUID,
        body_hash: str,
        result: dict[str, Any],
        now: datetime,
    ) -> None:
        self.session.add(
            ReviewEventRecord(
                project_id=event.project_id,
                event_id=event.event_id,
                item_id=event.item_id,
                actor_id=actor_id,
                principal=principal,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                received_at=now,
                body_hash=body_hash,
                result_json=json.dumps(result),
            )
        )
        self.session.flush()
