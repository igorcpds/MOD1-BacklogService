"""Human-approved initial backlog proposals from bounded authorized context."""

import hashlib
import json
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError

from backlog_service.domain import (
    Conflict,
    DependencyUnavailable,
    GeneratedProposal,
    Item,
    ProjectContext,
    Recommendation,
)
from backlog_service.item_service import ItemsService


class ProjectSource(Protocol):
    def get(self, project_id: UUID) -> dict[str, Any]: ...


class ProposalProvider(Protocol):
    model: str
    provider: str
    simulated: bool

    def generate(self, kind: str, context: dict[str, Any]) -> object: ...


def fingerprint(context: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(context, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


class RecommendationsService:
    def __init__(
        self, items: ItemsService, source: ProjectSource, provider: ProposalProvider
    ) -> None:
        self.items, self.source, self.provider = items, source, provider
        self.repository = items.repository

    def context(
        self, context: ProjectContext, constraints: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        project = self.source.get(context.project_id)
        if (
            not isinstance(project.get("id"), str)
            or project["id"] != str(context.project_id)
            or type(project.get("version")) is not int
            or project["version"] < 1
            or not isinstance(project.get("description"), str)
        ):
            raise DependencyUnavailable("Service temporarily unavailable")
        safe_project = {
            key: project[key]
            for key in (
                "id",
                "version",
                "name",
                "description",
                "scope",
                "tags",
                "technology_stack",
                "technical_requirements",
                "constraints",
            )
            if key in project
        }
        snapshot = {
            "project": safe_project,
            "items": [
                {
                    "id": str(i.id),
                    "title": i.title,
                    "kind": i.kind,
                    "status": i.status,
                    "version": i.version,
                }
                for i in self.repository.all_items(context.project_id)
            ],
            "constraints": constraints or {},
        }
        if len(json.dumps(snapshot, ensure_ascii=False).encode()) > 65536:
            raise Conflict("Recommendation context exceeds 64 KiB")
        return snapshot

    def generate(
        self, context: ProjectContext, constraints: dict[str, Any] | None = None
    ) -> Recommendation:
        context.require("backlog:create")
        if context.archived or context.project_status not in {"active", "planned"}:
            raise Conflict("Project is read only")
        snapshot = self.context(context, constraints)
        try:
            proposal = GeneratedProposal.model_validate(
                self.provider.generate("initial_backlog", snapshot)
            )
            allowed_evidence = {"project." + key for key in snapshot["project"]} | {
                "items." + item["id"] for item in snapshot["items"]
            }
            if any(evidence not in allowed_evidence for evidence in proposal.evidence):
                raise ValueError("Unknown evidence")
        except (ValidationError, ValueError, TypeError):
            raise DependencyUnavailable("Invalid recommendation provider response") from None
        with self.items.mutation(context, "backlog:create"):
            if fingerprint(self.context(context, constraints)) != fingerprint(snapshot):
                raise Conflict("Recommendation source changed")
            rec = Recommendation(
                id=uuid4(),
                project_id=context.project_id,
                created_by=context.actor_id,
                created_at=self.items.clock(),
                model=self.provider.model,
                provider=self.provider.provider,
                simulated=self.provider.simulated,
                summary=proposal.summary,
                justification=proposal.justification,
                evidence=proposal.evidence,
                suggestions=[s.model_dump(mode="json") for s in proposal.suggestions],
                context_version=fingerprint(snapshot),
            )
            self.repository.save_recommendation(rec, context.actor_id, self.items.clock())
            self.repository.store_constraints(rec.id, constraints or {})
        return rec

    def get(self, context: ProjectContext, recommendation_id: UUID) -> Recommendation:
        context.require("backlog:read")
        return self.repository.get_recommendation(context.project_id, recommendation_id)

    def list(self, context: ProjectContext, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        context.require("backlog:read")
        return self.repository.recommendations(context.project_id, limit, offset)

    def decide(
        self,
        context: ProjectContext,
        recommendation_id: UUID,
        expected_version: int,
        *,
        approve: bool,
    ) -> Recommendation:
        expired = False
        with self.items.mutation(context, "backlog:create") as mutation:
            rec = self.repository.get_recommendation(context.project_id, recommendation_id)
            target = "approved" if approve else "rejected"
            if rec.status == target:
                if expected_version not in {rec.version, rec.version - 1}:
                    raise Conflict("Recommendation version conflict")
                mutation.changed = False
                return rec
            if rec.status != "pending" or rec.version != expected_version:
                raise Conflict("Recommendation version conflict")
            if approve:
                constraints = self.repository.recommendation_constraints(rec.id)
                if fingerprint(self.context(context, constraints)) != rec.context_version:
                    expired = True
                else:
                    try:
                        proposal = GeneratedProposal.model_validate(
                            {
                                "summary": rec.summary,
                                "justification": rec.justification,
                                "evidence": rec.evidence,
                                "suggestions": rec.suggestions,
                            }
                        )
                    except ValidationError:
                        raise Conflict("Recommendation content invalid") from None
                    applied: list[UUID] = []
                    for draft in proposal.suggestions:
                        self.items.validate_references(context, draft)
                        now = self.items.clock()
                        item = Item(
                            id=uuid4(),
                            project_id=context.project_id,
                            created_by=context.actor_id,
                            created_at=now,
                            updated_at=now,
                            status="todo",
                            position=len(self.repository.all_items(context.project_id)),
                            **draft.model_dump(),
                        )
                        self.repository.save_item(
                            item,
                            context.actor_id,
                            now,
                            new=True,
                            action="recommendation_approved",
                            diff={"recommendation_id": {"before": None, "after": str(rec.id)}},
                        )
                        applied.append(item.id)
                    rec = rec.model_copy(update={"applied_item_ids": applied})
            rec = rec.model_copy(
                update={"status": "expired" if expired else target, "version": rec.version + 1}
            )
            self.repository.save_recommendation(rec, context.actor_id, self.items.clock())
        if expired:
            raise Conflict("Recommendation source changed; generate a new proposal")
        return rec
