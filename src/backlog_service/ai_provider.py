"""Configurable structured provider; no retries, credentials remain server-side."""

import json
from typing import Any

import httpx

from backlog_service.config import Settings
from backlog_service.domain import DependencyUnavailable


class HTTPProposalProvider:
    provider = "generic-http"

    def __init__(self, client: httpx.Client, settings: Settings) -> None:
        self.client, self.settings = client, settings
        self.model, self.simulated = settings.ai_model, settings.ai_simulated
        if self.simulated:
            self.provider = "local-simulated-http"

    def generate(self, kind: str, context: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.ai_base_url or not self.model:
            raise DependencyUnavailable("Recommendation provider is not configured")
        try:
            if len(json.dumps(context, allow_nan=False).encode()) > 65536:
                raise ValueError
            headers = {"Content-Type": "application/json"}
            if self.settings.ai_api_key:
                headers["Authorization"] = "Bearer " + self.settings.ai_api_key.get_secret_value()
            with self.client.stream(
                "POST",
                self.settings.ai_base_url + "/generate",
                headers=headers,
                json={"schema_version": 1, "kind": kind, "model": self.model, "context": context},
                timeout=self.settings.ai_timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise ValueError
                body = bytearray()
                for part in response.iter_bytes():
                    body.extend(part)
                    if len(body) > 262144:
                        raise ValueError
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (httpx.HTTPError, ValueError, TypeError):
            raise DependencyUnavailable("Recommendation provider unavailable or invalid") from None
