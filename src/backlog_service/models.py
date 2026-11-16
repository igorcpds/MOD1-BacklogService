from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class StoryRecord(Base):
    __tablename__ = "stories"
    __table_args__ = {"schema": "backlog"}
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    kind: Mapped[str] = mapped_column(String(10), default="story", server_default="story")
    persona: Mapped[str] = mapped_column(Text, default="", server_default="")
    action: Mapped[str] = mapped_column(Text, default="", server_default="")
    benefit: Mapped[str] = mapped_column(Text, default="", server_default="")
    guided: Mapped[bool] = mapped_column(default=False, server_default="false")
    epic_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    parent_story_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    moscow_priority: Mapped[str | None] = mapped_column(String(10), nullable=True)
    estimate_value: Mapped[str | None] = mapped_column(String(32), nullable=True)
    estimate_unit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    assignee_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    is_blocked: Mapped[bool] = mapped_column(default=False, server_default="false")
    blocked_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    position: Mapped[int] = mapped_column(default=0, server_default="0")


class ProjectOrderRecord(Base):
    __tablename__ = "project_orders"
    __table_args__ = {"schema": "backlog"}
    project_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(default=0)


class DependencyRecord(Base):
    __tablename__ = "item_dependencies"
    __table_args__ = {"schema": "backlog"}
    project_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    depends_on_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)


class HistoryRecord(Base):
    __tablename__ = "item_history"
    __table_args__ = {"schema": "backlog"}
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    diff_json: Mapped[str] = mapped_column(Text)


class RecommendationRecord(Base):
    __tablename__ = "recommendations"
    __table_args__ = {"schema": "backlog"}
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10))
    version: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[str] = mapped_column(Text)
    constraints_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")


class RecommendationEventRecord(Base):
    __tablename__ = "recommendation_events"
    __table_args__ = {"schema": "backlog"}
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    recommendation_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(10))
    version: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewEventRecord(Base):
    __tablename__ = "code_review_events"
    __table_args__ = {"schema": "backlog"}
    project_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    principal: Mapped[str] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    body_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)


class NotificationDeliveryRecord(Base):
    """External delivery only; independent of internal per-user notifications."""

    __tablename__ = "module6_notification_outbox"
    __table_args__ = {"schema": "backlog"}
    event_id: Mapped[str] = mapped_column(String(140), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(nullable=True)


class Module4ReviewRecord(Base):
    __tablename__ = "module4_reviews"
    __table_args__ = (
        UniqueConstraint("project_id", "item_id", "request_id", name="uq_module4_item_request"),
        {"schema": "backlog"},
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    request_id: Mapped[UUID] = mapped_column(Uuid)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[str] = mapped_column(Text)
