"""Module4 request/result data. Pure validation, without HTTP or persistence."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

Architecture = Literal["multicamadas", "clean", "mvc", "hexagonal", "onion"]


class ReviewFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    caminho: str = Field(min_length=1, max_length=240)
    conteudo: str = Field(max_length=100000)

    @field_validator("caminho")
    @classmethod
    def python_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value.endswith(".py")
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in value
            or ":" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("Use a relative Python file path")
        return value


class Module4Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    pr_url: str | None = Field(default=None, max_length=500)
    arquivos: list[ReviewFile] | None = Field(default=None, min_length=1, max_length=20)
    arquitetura: Architecture = "multicamadas"
    usar_ia: bool = False

    @field_validator("pr_url")
    @classmethod
    def github_pr(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        parts = parsed.path.strip("/").split("/")
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.query
            or parsed.fragment
            or len(parts) != 4
            or any(not part or part in {".", ".."} for part in parts)
            or parts[2] != "pull"
            or not parts[3].isascii()
            or not parts[3].isdigit()
            or int(parts[3]) < 1
            or any(char in value for char in ("%", "\\", "?", "#"))
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("Use a GitHub HTTPS pull request URL")
        return value

    @model_validator(mode="after")
    def one_bounded_source(self) -> "Module4Draft":
        if bool(self.pr_url) == bool(self.arquivos):
            raise ValueError("Supply exactly one review source")
        if self.arquivos:
            if sum(len(file.conteudo.encode("utf-8")) for file in self.arquivos) > 100000:
                raise ValueError("Code exceeds the supported byte limit")
            if len({file.caminho for file in self.arquivos}) != len(self.arquivos):
                raise ValueError("Duplicate file paths")
        return self


class Finding(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    arquivo: str = Field(min_length=1, max_length=500)
    linha: int | None = Field(default=None, ge=1)
    categoria: str = Field(min_length=1, max_length=200)
    gravidade: str = Field(min_length=1, max_length=80)
    titulo: str = Field(min_length=1, max_length=1000)
    sugestao: str = Field(max_length=10000)


class AIReview(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    status: str = Field(min_length=1, max_length=200)
    texto: str = Field(max_length=100000)


class Module4Review(BaseModel):
    model_config = ConfigDict(
        extra="ignore", strict=True, hide_input_in_errors=True, allow_inf_nan=False
    )
    id: str = Field(pattern=r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
    criado_em: datetime
    arquitetura: Architecture
    arquivos: int = Field(ge=1, le=20)
    achados: list[Finding] = Field(max_length=2000)
    testes: list[JsonValue] = Field(max_length=1000)
    testes_executados: bool
    pr: JsonValue
    ia: AIReview
    markdown: str = Field(max_length=200000)

    @field_validator("testes", "pr", mode="before")
    @classmethod
    def finite_json_values(cls, value: object) -> object:
        remaining = [value]
        while remaining:
            current = remaining.pop()
            if isinstance(current, float) and not isfinite(current):
                raise ValueError("Provider JSON numbers must be finite")
            if isinstance(current, list):
                remaining.extend(current)
            elif isinstance(current, dict):
                remaining.extend(current.values())
        return value

    @field_validator("criado_em")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Review timestamp requires a timezone")
        return value


@dataclass(frozen=True)
class Module4Outcome:
    status: Literal["succeeded", "failed", "blocked", "uncertain"]
    review: Module4Review | None = None
    error: str | None = None
    http_status: int | None = None


class ReviewRequest(Module4Draft):
    request_id: UUID
    expected_version: int = Field(ge=1)

    @field_validator("request_id", mode="before")
    @classmethod
    def request_uuid(cls, value: object) -> UUID:
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            return UUID(value)
        raise ValueError("Use a request UUID")

    def provider_draft(self) -> Module4Draft:
        return Module4Draft.model_validate(
            self.model_dump(exclude={"request_id", "expected_version"})
        )


class ReviewSource(BaseModel):
    kind: Literal["files", "pull_request"]
    pr_url: str | None = None
    files: list[str] = Field(default_factory=list)


class CodeReview(BaseModel):
    id: UUID
    request_id: UUID
    project_id: UUID
    item_id: UUID
    status: Literal["pending", "succeeded", "failed", "blocked", "uncertain"]
    created_at: datetime
    updated_at: datetime
    source: ReviewSource
    arquitetura: Architecture
    usar_ia: bool
    result: Module4Review | None = None
    error: str | None = None
    status_effect: Literal[
        "started", "preserved", "not_applied_conflict", "not_applied_access", "not_applied_error"
    ] = "not_applied_error"
    item_version: int | None = None
