from sqlite3 import Connection

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateSchema

from backlog_service.config import Settings
from backlog_service.models import Base


def create_database_engine(settings: Settings) -> Engine:
    url = settings.database_url.get_secret_value()
    if url.startswith("sqlite:///"):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            hide_parameters=True,
        )

        @event.listens_for(engine, "connect")
        def unicode_lower(connection: Connection, connection_record: object) -> None:
            # SQLite's built-in lower is ASCII-only; retain Unicode search in local dev.
            connection.create_function("lower", 1, str.lower, deterministic=True)

        target = None
    else:
        engine = create_engine(
            url,
            pool_size=2,
            max_overflow=0,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
            hide_parameters=True,
        )
        target = settings.database_schema
    return engine.execution_options(schema_translate_map={"backlog": target})


def init_schema(engine: Engine, schema: str) -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema, if_not_exists=True))
    Base.metadata.create_all(engine)
