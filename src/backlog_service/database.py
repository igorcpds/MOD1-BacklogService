from sqlite3 import Connection

from sqlalchemy import Column, Engine, create_engine, event, select
from sqlalchemy.pool import QueuePool, StaticPool
from sqlalchemy.schema import CreateSchema

from backlog_service.config import Settings
from backlog_service.models import Base, StoryRecord


def check_readiness(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(select(StoryRecord.id).limit(1))


def create_database_engine(settings: Settings) -> Engine:
    url = settings.database_url.get_secret_value()
    if url.startswith("sqlite:///"):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if ":memory:" in url else QueuePool,
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
    migrate_schema(engine, schema)


def migrate_schema(engine: Engine, schema: str) -> None:
    """Explicit additive migration; never called by application startup."""
    from sqlalchemy import inspect, update
    from sqlalchemy.schema import CreateColumn

    target = schema if engine.dialect.name == "postgresql" else None
    with engine.begin() as connection:
        columns = {
            column["name"] for column in inspect(connection).get_columns("stories", schema=target)
        }
        quote = connection.dialect.identifier_preparer.quote
        table = (quote(target) + "." if target else "") + quote("stories")
        for column in StoryRecord.__table__.c:
            assert isinstance(column, Column)
            if column.name not in columns:
                ddl = str(CreateColumn(column).compile(dialect=connection.dialect))
                connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        if "position" not in columns:
            rows = connection.execute(
                select(StoryRecord.id, StoryRecord.project_id).order_by(
                    StoryRecord.project_id, StoryRecord.created_at, StoryRecord.id
                )
            ).all()
            positions: dict[object, int] = {}
            for identifier, project in rows:
                position = positions.get(project, 0)
                connection.execute(
                    update(StoryRecord)
                    .where(StoryRecord.id == identifier)
                    .values(position=position)
                )
                positions[project] = position + 1
