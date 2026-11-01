import re
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from backlog_service.domain import Status

LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr = Field(repr=False)
    database_schema: str = Field(default="backlog", pattern=r"^[a-z_][a-z0-9_]*$")
    jwt_issuer: str = Field(default="mod1-auth-local", min_length=1)
    jwt_audience: str = Field(default="engenharia-software-api", min_length=1)
    jwks_url: str = "http://127.0.0.1:8000/.well-known/jwks.json"
    projects_api_base_url: str = "http://127.0.0.1:8001"
    auth_api_base_url: str = "http://127.0.0.1:8000"
    auth_session_check_enabled: bool = True
    projects_legacy_access_enabled: bool = False
    code_review_enabled: bool = False
    code_review_key: SecretStr | None = Field(
        default=None, min_length=32, max_length=512, repr=False
    )
    code_review_project_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    code_review_event_mapping: dict[str, Status] = Field(default_factory=dict, max_length=100)

    @field_validator("code_review_event_mapping")
    @classmethod
    def bounded_review_mapping(cls, value: dict[str, Status]) -> dict[str, Status]:
        if any(not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,80}", key) for key in value):
            raise ValueError("Invalid code review event mapping")
        return value

    ai_base_url: str | None = None
    ai_model: str = Field(default="", max_length=200)
    ai_api_key: SecretStr | None = Field(default=None, repr=False)
    ai_simulated: bool = False
    ai_timeout_seconds: int = Field(default=30, ge=1, le=60)

    @field_validator("ai_base_url")
    @classmethod
    def validate_ai_url(cls, value: str | None) -> str | None:
        return cls.validate_projects_url(value) if value else None

    @model_validator(mode="after")
    def simulated_only_loopback(self) -> "Settings":
        if self.ai_simulated and (
            not self.ai_base_url or urlsplit(self.ai_base_url).hostname not in LOOPBACK
        ):
            raise ValueError("Simulated provider requires explicit loopback URL")
        return self

    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173"])

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            parsed = make_url(value.get_secret_value())
        except Exception:
            raise ValueError("Invalid database configuration") from None
        if parsed.drivername == "sqlite" and value.get_secret_value().startswith("sqlite:///"):
            return value
        if parsed.drivername != "postgresql+psycopg" or not parsed.host:
            raise ValueError("Use PostgreSQL/psycopg or isolated SQLite for tests")
        if "host" in parsed.query or "hostaddr" in parsed.query:
            raise ValueError("Configure database host only in the URL authority")
        if parsed.host not in LOOPBACK and (
            parsed.query.get("sslmode") != "verify-full" or not parsed.query.get("sslrootcert")
        ):
            raise ValueError(
                "Remote PostgreSQL requires verify-full and a trusted root certificate"
            )
        return value

    @field_validator("jwks_url")
    @classmethod
    def validate_jwks(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in LOOPBACK)
        ):
            raise ValueError("Configure a trusted HTTPS JWKS URL or HTTP loopback")
        return value

    @field_validator("projects_api_base_url", "auth_api_base_url")
    @classmethod
    def validate_projects_url(cls, value: str) -> str:
        cls.validate_jwks(value)
        if urlsplit(value).query:
            raise ValueError("Projects base URL must not contain a query")
        return value.rstrip("/")

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS requires explicit HTTP origins without paths")
        return values
