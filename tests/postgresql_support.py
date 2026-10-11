from sqlalchemy.engine import make_url


def require_local(url: str) -> None:
    parsed = make_url(url)
    if (
        parsed.drivername != "postgresql+psycopg"
        or parsed.host not in ("localhost", "127.0.0.1", "::1")
        or any(
            name.lower() in {"host", "hostaddr", "service", "servicefile", "port"}
            for name in parsed.query
        )
    ):
        raise ValueError("Disposable integration requires explicit loopback PostgreSQL")
