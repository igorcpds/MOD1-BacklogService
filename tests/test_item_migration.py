from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from backlog_service.database import create_database_engine, init_schema
from backlog_service.item_repository import ItemRepository


def test_explicit_migration_preserves_old_story(settings):
    engine = create_database_engine(settings)
    item, project, actor = uuid4(), uuid4(), uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE stories (id CHAR(32) PRIMARY KEY, project_id CHAR(32) NOT NULL, "
                "created_by CHAR(32) NOT NULL, title VARCHAR(120) NOT NULL, "
                "description TEXT NOT NULL, "
                "acceptance_criteria TEXT NOT NULL, priority VARCHAR(10) NOT NULL, "
                "status VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO stories VALUES (:id,:project,:actor,'Old story','legacy','criteria',"
                "'high','done','2026-10-11 00:00:00','2026-10-11 00:00:00')"
            ),
            {"id": item.hex, "project": project.hex, "actor": actor.hex},
        )
    init_schema(engine, "backlog")
    init_schema(engine, "backlog")
    with Session(engine) as session:
        migrated = ItemRepository(session).item(project, item)
        assert migrated.id == item and migrated.description == "legacy"
        assert migrated.kind == "story" and migrated.moscow_priority is None
        assert migrated.persona == "" and migrated.status == "done"
        assert ItemRepository(session).history(project, item, 20, 0)["total"] == 0
    engine.dispose()
