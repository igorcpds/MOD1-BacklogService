"""Dedicated integration credential gate; user authorization is checked separately."""

from hmac import compare_digest
from uuid import UUID

from backlog_service.config import Settings
from backlog_service.domain import (
    DependencyUnavailable,
    InsufficientProjectPermissions,
    ReviewPrincipal,
)
from backlog_service.security import AuthenticationRejected


def authorize_review_principal(
    settings: Settings, project_id: UUID, supplied_keys: list[str]
) -> ReviewPrincipal:
    key = settings.code_review_key.get_secret_value() if settings.code_review_key else ""
    if (
        not settings.code_review_enabled
        or not key
        or len(key) < 32
        or not settings.code_review_event_mapping
        or not settings.code_review_project_ids
    ):
        raise DependencyUnavailable("Code review integration is not configured")
    if (
        len(supplied_keys) != 1
        or len(supplied_keys[0]) > 512
        or not compare_digest(supplied_keys[0].encode(), key.encode())
    ):
        raise AuthenticationRejected("Authentication required")
    if project_id not in settings.code_review_project_ids:
        raise InsufficientProjectPermissions("Insufficient project permissions")
    return ReviewPrincipal("code-review", frozenset(settings.code_review_project_ids))
