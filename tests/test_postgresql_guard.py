import pytest
from postgresql_support import require_local


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@remote.example/db",
        "postgresql+psycopg://u:p@localhost/db?host=remote.example",
        "postgresql+psycopg://u:p@localhost/db?hostaddr=1.2.3.4",
        "postgresql+psycopg://u:p@localhost/db?service=production",
        "postgresql+psycopg://u:p@localhost/db?port=5432,5433",
        "postgresql+psycopg:///db",
        "sqlite:///:memory:",
    ],
)
def test_rejects_remote_socket_and_connection_overrides(url):
    with pytest.raises(ValueError):
        require_local(url)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_accepts_explicit_loopback_only(host):
    require_local(f"postgresql+psycopg://u:p@{host}/disposable")
