"""Own-schema persistence for durable, item-scoped Module4 attempts."""

from uuid import UUID

from sqlalchemy import func, select

from backlog_service.domain import Conflict, MissingItem
from backlog_service.item_repository import ItemRepository
from backlog_service.models import Module4ReviewRecord
from backlog_service.module4_domain import CodeReview


class Module4Repository(ItemRepository):
    def by_request(
        self, project_id: UUID, item_id: UUID, request_id: UUID, fingerprint: str | None = None
    ) -> CodeReview | None:
        record = self.session.scalar(
            select(Module4ReviewRecord)
            .where(
                Module4ReviewRecord.project_id == project_id,
                Module4ReviewRecord.item_id == item_id,
                Module4ReviewRecord.request_id == request_id,
            )
            .execution_options(populate_existing=True)
        )
        if record is None:
            return None
        if fingerprint is not None and record.fingerprint != fingerprint:
            raise Conflict("Request identifier already used for different content")
        return CodeReview.model_validate_json(record.payload_json)

    def save_review(self, review: CodeReview, fingerprint: str | None = None) -> None:
        record = self.session.get(Module4ReviewRecord, review.id)
        if record is None:
            assert fingerprint is not None
            record = Module4ReviewRecord(
                id=review.id,
                project_id=review.project_id,
                item_id=review.item_id,
                request_id=review.request_id,
                fingerprint=fingerprint,
                created_at=review.created_at,
            )
            self.session.add(record)
        record.payload_json = review.model_dump_json()
        self.session.flush()

    def review(self, project_id: UUID, item_id: UUID, review_id: UUID) -> CodeReview:
        record = self.session.scalar(
            select(Module4ReviewRecord)
            .where(
                Module4ReviewRecord.project_id == project_id,
                Module4ReviewRecord.item_id == item_id,
                Module4ReviewRecord.id == review_id,
            )
            .execution_options(populate_existing=True)
        )
        if record is None:
            raise MissingItem("Review unavailable")
        return CodeReview.model_validate_json(record.payload_json)

    def reviews(
        self, project_id: UUID, item_id: UUID, limit: int, offset: int
    ) -> tuple[list[CodeReview], int]:
        condition = (Module4ReviewRecord.project_id == project_id) & (
            Module4ReviewRecord.item_id == item_id
        )
        total = (
            self.session.scalar(
                select(func.count()).select_from(Module4ReviewRecord).where(condition)
            )
            or 0
        )
        records = self.session.scalars(
            select(Module4ReviewRecord)
            .where(condition)
            .order_by(Module4ReviewRecord.created_at.desc(), Module4ReviewRecord.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return [CodeReview.model_validate_json(row.payload_json) for row in records], total
