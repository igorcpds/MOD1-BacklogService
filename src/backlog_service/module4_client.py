"""Bounded BasicAuth Module4 transport; never retries an analysis POST."""

import asyncio
import json
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from backlog_service.module4_domain import Module4Draft, Module4Outcome, Module4Review

OFFICIAL_HOST = "revisor-codigo-ia-gio-ach9dbg3g9ekazf3.chilecentral-01.azurewebsites.net"


def reject_nonfinite(value: str) -> None:
    raise ValueError("Invalid non-finite provider value")


def trusted_base_url(value: str) -> str:
    parsed = urlsplit(value)
    official = (
        parsed.scheme == "https" and parsed.hostname == OFFICIAL_HOST and parsed.port in {None, 443}
    )
    local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        not (official or local)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or any(char in value for char in ("?", "#", "\\", "%"))
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Use the Module4 HTTPS origin or explicit HTTP loopback")
    return value.rstrip("/")


class Module4Client:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = 60,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = trusted_base_url(base_url)
        self.username, self.password = username, password
        self.timeout, self.transport = timeout, transport

    def analyze(self, draft: Module4Draft) -> Module4Outcome:
        try:
            return asyncio.run(asyncio.wait_for(self._analyze(draft), timeout=self.timeout))
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return Module4Outcome("failed", error="connection_unavailable")
        except (httpx.HTTPError, TimeoutError):
            return Module4Outcome("uncertain", error="delivery_uncertain")

    async def _analyze(self, draft: Module4Draft) -> Module4Outcome:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=5),
            trust_env=False,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            async with client.stream(
                "POST",
                self.base_url + "/api/analisar",
                json=draft.model_dump(mode="json", exclude_none=True),
                auth=httpx.BasicAuth(self.username, self.password),
                headers={"Accept": "application/json", "User-Agent": "mod1-backlog/code-review"},
            ) as response:
                code = response.status_code
                if code in {401, 403, 429}:
                    return Module4Outcome("blocked", error="provider_rejected", http_status=code)
                if code not in {200, 201}:
                    status: Literal["uncertain", "failed"] = (
                        "uncertain" if code >= 500 or 200 <= code < 300 else "failed"
                    )
                    return Module4Outcome(status, error="provider_response", http_status=code)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1048576:
                        return Module4Outcome(
                            "uncertain", error="response_too_large", http_status=code
                        )
                try:
                    json.loads(body, parse_constant=reject_nonfinite)
                    result = Module4Review.model_validate_json(bytes(body))
                    if result.arquitetura != draft.arquitetura or (
                        draft.arquivos and result.arquivos != len(draft.arquivos)
                    ):
                        raise ValueError("Review metadata differs from the submitted source")
                except (ValidationError, ValueError, TypeError, RecursionError):
                    return Module4Outcome("uncertain", error="invalid_response", http_status=code)
                return Module4Outcome("succeeded", review=result, http_status=code)
