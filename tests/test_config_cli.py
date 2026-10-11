import pytest
from pydantic import ValidationError

from backlog_service.cli import main
from backlog_service.config import Settings


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@remote/db?sslmode=require",
        "postgresql+psycopg://u:p@remote/db?sslmode=verify-full",
        "postgresql+psycopg://u:p@localhost/db?host=remote",
        "postgresql+psycopg://u:p@localhost/db?hostaddr=192.0.2.1",
        "mysql://u:p@localhost/db",
    ],
)
def test_database_configuration_rejects_unsafe_urls(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


@pytest.mark.parametrize(
    "field,url",
    [
        ("projects_api_base_url", "http://remote.invalid"),
        ("projects_api_base_url", "https://user:secret@host.invalid"),
        ("projects_api_base_url", "https://host.invalid?target=other"),
        ("jwks_url", "http://remote.invalid/jwks"),
        ("cors_origins", ["*"]),
    ],
)
def test_trusted_urls_and_origins(field, url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite:///:memory:", **{field: url})


def test_init_idempotent_preserves_data(monkeypatch, settings, service, project_id, actor_id):
    from backlog_service.domain import StoryDraft

    story = service.create(project_id, actor_id, StoryDraft(title="Não apagar"))
    monkeypatch.setenv("DATABASE_URL", settings.database_url.get_secret_value())
    monkeypatch.setenv("DATABASE_SCHEMA", "backlog")
    assert main(["init"]) == main(["init"]) == 0
    assert service.get(project_id, story.id).title == "Não apagar"
