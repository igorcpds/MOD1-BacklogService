"""Synchronous review coordination without HTTP, ORM or long-running write locks."""

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from backlog_service.domain import Conflict, DependencyUnavailable, ProjectContext
from backlog_service.item_service import WriteControl, utc_now
from backlog_service.module4_domain import (
    CodeReview,
    Module4Draft,
    Module4Outcome,
    ReviewRequest,
    ReviewSource,
)
from backlog_service.module4_repository import Module4Repository


class ReviewProvider(Protocol):
    def analyze(self, draft: Module4Draft) -> Module4Outcome: ...


@dataclass
class ReviewTransaction:
    committed: bool = False


class Module4Service:
    def __init__(
        self,
        repository: Module4Repository,
        provider: ReviewProvider | None,
        fresh_context: Callable[[], ProjectContext],
        *,
        enabled: bool = False,
        control: WriteControl | None = None,
    ) -> None:
        self.repository, self.provider = repository, provider
        self.fresh_context, self.enabled, self.control = fresh_context, enabled, control

    @staticmethod
    def writable(context: ProjectContext) -> None:
        context.require("backlog:read")
        context.require("backlog:update_status")
        if context.archived or context.project_status not in {"active", "planned"}:
            raise Conflict("Project is read only")

    @contextmanager
    def transaction(
        self, context: ProjectContext, *, revalidate: bool = False
    ) -> Iterator[ReviewTransaction]:
        self.writable(context)
        lease = self.control.acquire(context.project_id) if self.control else None
        state = ReviewTransaction()
        try:
            if revalidate:
                fresh = self.fresh_context()
                if fresh.project_id != context.project_id or fresh.actor_id != context.actor_id:
                    raise Conflict("Current access changed")
                self.writable(fresh)
            self.repository.lock(context.project_id)
            yield state
            self.repository.commit()
            state.committed = True
        except BaseException:
            self.repository.rollback()
            raise
        finally:
            if lease is not None and self.control is not None:
                self.control.release(context.project_id, lease)

    def analyze(self, context: ProjectContext, item_id: UUID, draft: ReviewRequest) -> CodeReview:
        self.writable(context)
        if not self.enabled or self.provider is None:
            raise DependencyUnavailable("Code review provider is disabled")
        fingerprint = hashlib.sha256(
            json.dumps(
                draft.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        with self.transaction(context):
            previous = self.repository.by_request(
                context.project_id, item_id, draft.request_id, fingerprint
            )
            if previous is not None:
                return previous
            item = self.repository.item(context.project_id, item_id)
            if item.version != draft.expected_version:
                raise Conflict("Item version conflict")
            now = utc_now()
            review = CodeReview(
                id=uuid4(),
                request_id=draft.request_id,
                project_id=context.project_id,
                item_id=item_id,
                status="pending",
                created_at=now,
                updated_at=now,
                source=ReviewSource(
                    kind="pull_request" if draft.pr_url else "files",
                    pr_url=draft.pr_url,
                    files=[file.caminho for file in draft.arquivos or []],
                ),
                arquitetura=draft.arquitetura,
                usar_ia=draft.usar_ia,
                item_version=item.version,
            )
            self.repository.save_review(review, fingerprint)
        # Pending is committed and lease released before the only external POST.
        outcome = self.provider.analyze(draft.provider_draft())
        review = review.model_copy(
            update={
                "status": outcome.status,
                "result": outcome.review,
                "error": outcome.error,
                "updated_at": utc_now(),
            }
        )
        self.repository.save_review(review)
        self.repository.commit()
        final = ReviewTransaction()
        access_confirmed = False
        try:
            fresh = self.fresh_context()
            if fresh.project_id != context.project_id or fresh.actor_id != context.actor_id:
                raise Conflict("Current access changed")
            self.writable(fresh)
            with self.transaction(fresh, revalidate=True) as final:
                access_confirmed = True
                # Resolve after locking, bypassing stale ORM identity-map values.
                item = self.repository.item(fresh.project_id, item_id)
                effect = "not_applied_error"
                if outcome.status == "succeeded" and outcome.review is not None:
                    if item.version != draft.expected_version:
                        effect = "not_applied_conflict"
                    elif item.status != "todo":
                        effect = "preserved"
                    else:
                        now = utc_now()
                        item = item.model_copy(
                            update={
                                "status": "in_progress",
                                "version": item.version + 1,
                                "updated_at": now,
                            }
                        )
                        self.repository.save_item(
                            item,
                            fresh.actor_id,
                            now,
                            diff={"status": {"before": "todo", "after": "in_progress"}},
                        )
                        self.repository.advance(fresh.project_id)
                        effect = "started"
                review = review.model_copy(
                    update={
                        "status_effect": effect,
                        "item_version": item.version,
                        "updated_at": utc_now(),
                    }
                )
                self.repository.save_review(review)
        except Exception:
            if final.committed:
                raise
            # Outcome stays durable, but never expose it after lost current authorization.
            self.repository.rollback()
            review = review.model_copy(
                update={
                    "status_effect": "not_applied_error"
                    if access_confirmed
                    else "not_applied_access",
                    "item_version": None,
                    "updated_at": utc_now(),
                }
            )
            self.repository.save_review(review)
            self.repository.commit()
            raise
        return review

    def list(
        self, context: ProjectContext, item_id: UUID, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        context.require("backlog:read")
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        self.repository.item(context.project_id, item_id)
        reviews, total = self.repository.reviews(context.project_id, item_id, limit, offset)
        return {
            "items": reviews,
            "total": total,
            "limit": limit,
            "offset": offset,
            "enabled": self.enabled,
        }

    def get(self, context: ProjectContext, item_id: UUID, review_id: UUID) -> CodeReview:
        context.require("backlog:read")
        self.repository.item(context.project_id, item_id)
        return self.repository.review(context.project_id, item_id, review_id)
