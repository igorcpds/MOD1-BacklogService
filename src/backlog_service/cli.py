import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from backlog_service.config import Settings
from backlog_service.database import create_database_engine, init_schema


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare only the backlog schema")
    parser.add_subparsers(dest="command", required=True).add_parser("init")
    parser.parse_args(argv)
    try:
        settings = Settings()
        engine = create_database_engine(settings)
        try:
            init_schema(engine, settings.database_schema)
        finally:
            engine.dispose()
        print("Backlog schema ready; existing data preserved.")
        return 0
    except (ValidationError, SQLAlchemyError, OSError):
        print("Configuration or database unavailable.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
