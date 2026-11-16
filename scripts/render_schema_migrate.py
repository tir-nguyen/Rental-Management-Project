"""Preflight or create the approved Render PostgreSQL schema."""

import argparse
from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from models import db
from production_database_config import (
    load_production_target,
    validate_connected_target,
)


EXPECTED_REVISION = "f5d032bff585"
VERSION_TABLE = "alembic_version"


def inspect_schema(connection):
    tables = set(inspect(connection).get_table_names(schema="public"))
    expected_tables = set(db.metadata.tables)
    if not tables:
        return "blank", tables, None
    if tables != expected_tables | {VERSION_TABLE}:
        raise RuntimeError(
            "Production public schema is neither blank nor the exact expected "
            f"schema. Missing: {sorted((expected_tables | {VERSION_TABLE}) - tables)}; "
            f"unexpected: {sorted(tables - expected_tables - {VERSION_TABLE})}."
        )

    version_table = connection.dialect.identifier_preparer.quote_schema("public")
    revision = connection.execute(
        text(f'SELECT version_num FROM {version_table}."{VERSION_TABLE}"')
    ).scalars().all()
    if revision != [EXPECTED_REVISION]:
        raise RuntimeError(
            f"Unexpected Alembic revision {revision!r}; expected {EXPECTED_REVISION}."
        )
    return "ready", tables, revision[0]


def migrate_schema(apply, confirmation):
    target = load_production_target(
        confirmation=confirmation,
        require_confirmation=apply,
    )
    engine = create_engine(target.sqlalchemy_url)
    try:
        with engine.connect() as connection:
            validate_connected_target(connection, target)
            state, tables, revision = inspect_schema(connection)
            if not apply:
                print(f"Target: {target.confirmation}")
                print(f"Schema state: {state}")
                print(f"Tables found: {len(tables)}")
                if revision:
                    print(f"Alembic revision: {revision}")
                print("Preflight completed; no database changes were made.")
                return
            if state != "blank":
                raise RuntimeError(
                    "Schema apply requires a completely blank public schema; "
                    "no changes were made."
                )

        os.environ["RENTAL_PRODUCTION_CONFIRM_TARGET"] = target.confirmation
        config = Config(str(PROJECT_ROOT / "migrations_production" / "alembic.ini"))
        command.upgrade(config, "f5d032bff585")

        with engine.connect() as connection:
            validate_connected_target(connection, target)
            state, tables, revision = inspect_schema(connection)
            if state != "ready" or revision != EXPECTED_REVISION:
                raise RuntimeError(
                    "Post-migration verification failed. Preserve the database and "
                    "backup for investigation; do not retry blindly."
                )
            print(
                f"Schema created and verified on {target.confirmation}: "
                f"{len(tables) - 1} application tables, revision {revision}."
            )
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="read-only target/schema preflight")
    mode.add_argument("--apply", action="store_true", help="create schema on a blank target")
    parser.add_argument(
        "--confirm-target",
        help="For --apply, type exactly the approved hostname/database.",
    )
    args = parser.parse_args()
    migrate_schema(args.apply, args.confirm_target)


if __name__ == "__main__":
    main()
