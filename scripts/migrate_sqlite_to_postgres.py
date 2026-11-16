"""Copy the project's SQLite database into an empty PostgreSQL schema."""

import os
import sys
from pathlib import Path

from sqlalchemy import URL, create_engine, func, inspect, select, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from alembic.config import Config
from alembic.script import ScriptDirectory
from database_config import (
    get_rental_test_postgresql_uri,
    validate_sqlite_source_path,
)
from models import db


CHUNK_SIZE = 500
ALEMBIC_VERSION_TABLE = "alembic_version"
EXPECTED_ALEMBIC_REVISION = "f5d032bff585"


def get_test_source_path():
    source_path = os.environ.get("RENTAL_SQLITE_SOURCE", "").strip()
    if not source_path:
        raise ValueError(
            "RENTAL_SQLITE_SOURCE must point to a separate SQLite test copy."
        )
    return validate_sqlite_source_path(source_path)


def validate_project_revision():
    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    project_head = ScriptDirectory.from_config(config).get_current_head()
    if project_head != EXPECTED_ALEMBIC_REVISION:
        raise RuntimeError(
            "The data migration script expects Alembic head "
            f"{EXPECTED_ALEMBIC_REVISION}, but the project migration head is "
            f"{project_head!r}. Update and review the import script before use."
        )


def create_read_only_source_engine(source_database):
    source_database = validate_sqlite_source_path(source_database)
    if not source_database.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {source_database}")

    source_url = URL.create(
        "sqlite+pysqlite",
        database=f"file:{source_database.as_posix()}?mode=ro",
        query={"uri": "true"},
    )
    return create_engine(source_url)


def validate_source(connection):
    inspector = inspect(connection)
    expected_tables = set(db.metadata.tables)
    source_tables = set(inspector.get_table_names())
    if source_tables != expected_tables:
        raise RuntimeError(
            "SQLite tables do not match the application schema. "
            f"Missing: {sorted(expected_tables - source_tables)}; "
            f"unexpected: {sorted(source_tables - expected_tables)}."
        )

    for table in db.metadata.sorted_tables:
        source_columns = {column["name"] for column in inspector.get_columns(table.name)}
        expected_columns = set(table.columns.keys())
        if source_columns != expected_columns:
            raise RuntimeError(
                f"SQLite columns do not match for {table.name}. "
                f"Missing: {sorted(expected_columns - source_columns)}; "
                f"unexpected: {sorted(source_columns - expected_columns)}."
            )

    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            f"SQLite source has {len(violations)} foreign-key violation(s); refusing to copy."
        )


def validate_target(connection, schema):
    validate_project_revision()
    identity = connection.execute(
        text(
            "SELECT current_database(), inet_server_addr(), "
            "inet_server_port(), current_schema()"
        )
    ).one()
    if (
        identity[0] != "rental_test"
        or str(identity[1]) not in ("127.0.0.1", "::1")
        or identity[2] != 5432
        or identity[3] != "public"
    ):
        raise RuntimeError(
            "Refusing migration operation: connected target must be "
            "localhost:5432/rental_test using the public schema."
        )

    inspector = inspect(connection)
    target_tables = set(inspector.get_table_names(schema=schema))
    expected_tables = set(db.metadata.tables)
    allowed_tables = expected_tables | {ALEMBIC_VERSION_TABLE}

    if ALEMBIC_VERSION_TABLE not in target_tables:
        raise RuntimeError(
            "PostgreSQL schema is not initialized. Run the reviewed Flask-Alembic "
            "migration before importing data."
        )
    if target_tables != allowed_tables:
        raise RuntimeError(
            "PostgreSQL schema contains missing or unexpected tables. "
            f"Missing: {sorted(allowed_tables - target_tables)}; "
            f"unexpected: {sorted(target_tables - allowed_tables)}."
        )

    preparer = connection.dialect.identifier_preparer
    version_table = (
        f"{preparer.quote_schema(schema)}."
        f"{preparer.quote(ALEMBIC_VERSION_TABLE)}"
    )
    versions = connection.execute(
        text(f"SELECT version_num FROM {version_table}")
    ).scalars().all()
    if versions != [EXPECTED_ALEMBIC_REVISION]:
        raise RuntimeError(
            "PostgreSQL Alembic revision does not match the required schema revision. "
            f"Expected {EXPECTED_ALEMBIC_REVISION}; found {versions!r}. "
            "Apply the reviewed project migrations before importing."
        )

    for table in db.metadata.sorted_tables:
        target_columns = {
            column["name"] for column in inspector.get_columns(table.name, schema=schema)
        }
        expected_columns = set(table.columns.keys())
        if target_columns != expected_columns:
            raise RuntimeError(
                f"PostgreSQL columns do not match for {table.name}. "
                f"Missing: {sorted(expected_columns - target_columns)}; "
                f"unexpected: {sorted(target_columns - expected_columns)}."
            )


def reset_sequences(connection, schema):
    preparer = connection.dialect.identifier_preparer
    for table in db.metadata.sorted_tables:
        primary_key = list(table.primary_key.columns)
        if len(primary_key) != 1:
            continue
        primary_key_column = primary_key[0]
        if not primary_key_column.autoincrement:
            continue

        qualified_table = (
            f"{preparer.quote_schema(schema)}.{preparer.quote(table.name)}"
        )
        sequence_name = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {
                "table_name": qualified_table,
                "column_name": primary_key_column.name,
            },
        ).scalar_one_or_none()
        if sequence_name is None:
            raise RuntimeError(
                f"No PostgreSQL sequence is associated with "
                f"{table.name}.{primary_key_column.name}."
            )

        max_id = connection.execute(
            select(func.max(primary_key_column)).select_from(table)
        ).scalar_one()
        expected_value = max_id if max_id is not None else 1
        expected_is_called = max_id is not None
        connection.execute(
            text(
                "SELECT setval(CAST(:sequence_name AS regclass), :last_value, :is_called)"
            ),
            {
                "sequence_name": sequence_name,
                "last_value": expected_value,
                "is_called": expected_is_called,
            },
        )
        sequence_parts = connection.execute(
            text(
                "SELECT namespace.nspname, sequence.relname "
                "FROM pg_class AS sequence "
                "JOIN pg_namespace AS namespace ON namespace.oid = sequence.relnamespace "
                "WHERE sequence.oid = CAST(:sequence_name AS regclass)"
            ),
            {"sequence_name": sequence_name},
        ).one_or_none()
        if sequence_parts is None:
            raise RuntimeError(
                f"Could not inspect sequence {sequence_name!r} after resetting it."
            )
        sequence_table = (
            f"{preparer.quote_schema(sequence_parts.nspname)}."
            f"{preparer.quote(sequence_parts.relname)}"
        )
        actual_value, actual_is_called = connection.execute(
            text(f"SELECT last_value, is_called FROM {sequence_table}")
        ).one()
        if (actual_value, actual_is_called) != (expected_value, expected_is_called):
            raise RuntimeError(
                f"Sequence {sequence_name!r} did not reset as expected: "
                f"expected ({expected_value}, {expected_is_called}), "
                f"found ({actual_value}, {actual_is_called})."
            )


def repair_sequences():
    target_uri = get_rental_test_postgresql_uri()
    target_engine = create_engine(target_uri)
    try:
        with target_engine.begin() as connection:
            schema = connection.execute(text("SELECT current_schema()")).scalar_one()
            validate_target(connection, schema)
            row_counts = [
                connection.execute(select(func.count()).select_from(table)).scalar_one()
                for table in db.metadata.sorted_tables
            ]
            if not any(row_counts):
                raise RuntimeError(
                    "All application tables are empty; refusing sequence-only repair. "
                    "Import test data first or verify RENTAL_TEST_DATABASE_URL."
                )
            reset_sequences(connection, schema)
        print("Sequence-only repair completed. Application data was not modified.")
    except Exception as error:
        raise RuntimeError(
            "Sequence-only repair failed; application rows were not modified by this "
            "repair. Correct the database/permission issue and rerun "
            "'python scripts/migrate_sqlite_to_postgres.py --repair-sequences'."
        ) from error
    finally:
        target_engine.dispose()


def migrate():
    target_uri = get_rental_test_postgresql_uri()
    source_path = get_test_source_path()
    target_engine = create_engine(target_uri)
    source_engine = None
    try:
        with target_engine.connect() as target_connection:
            schema = target_connection.execute(
                text("SELECT current_schema()")
            ).scalar_one()
            validate_target(target_connection, schema)
            table_counts = [
                target_connection.execute(
                    select(func.count()).select_from(table)
                ).scalar_one()
                for table in db.metadata.sorted_tables
            ]
            if any(table_counts):
                raise RuntimeError(
                    "PostgreSQL application tables are not empty; refusing to import."
                )

        source_engine = create_read_only_source_engine(source_path)
        with source_engine.connect() as source_connection:
            source_connection.exec_driver_sql("BEGIN")
            validate_source(source_connection)
            source_counts = {
                table.name: source_connection.execute(
                    select(func.count()).select_from(table)
                ).scalar_one()
                for table in db.metadata.sorted_tables
            }

            with target_engine.begin() as target_connection:
                schema = target_connection.execute(
                    text("SELECT current_schema()")
                ).scalar_one()
                validate_target(target_connection, schema)

                table_names = sorted(db.metadata.tables)
                quoted_tables = ", ".join(
                    target_connection.dialect.identifier_preparer.quote(name)
                    for name in table_names
                )
                target_connection.exec_driver_sql(
                    f"LOCK TABLE {quoted_tables} IN ACCESS EXCLUSIVE MODE"
                )

                for table in db.metadata.sorted_tables:
                    existing_rows = target_connection.execute(
                        select(func.count()).select_from(table)
                    ).scalar_one()
                    if existing_rows:
                        raise RuntimeError(
                            f"PostgreSQL table {table.name} is not empty "
                            f"({existing_rows} row(s)); refusing to import."
                        )

                imported_counts = {name: 0 for name in source_counts}
                for table in db.metadata.sorted_tables:
                    result = source_connection.execute(select(table))
                    while rows := result.mappings().fetchmany(CHUNK_SIZE):
                        target_connection.execute(table.insert(), [dict(row) for row in rows])
                        imported_counts[table.name] += len(rows)

                if imported_counts != source_counts:
                    raise RuntimeError(
                        "Imported row counts do not match the SQLite source. "
                        f"Source: {source_counts}; imported: {imported_counts}."
                    )

        for table_name in sorted(imported_counts):
            print(f"{table_name}: {imported_counts[table_name]} row(s)")
        print("Data import committed successfully.")

        try:
            with target_engine.begin() as sequence_connection:
                reset_sequences(sequence_connection, schema)
        except Exception as error:
            raise RuntimeError(
                "Data import has already committed, but sequence reset failed. "
                "The imported rows are preserved. Do not rerun the data import. "
                "After correcting the sequence/permission issue, run "
                "'python scripts/migrate_sqlite_to_postgres.py --repair-sequences' "
                "to reset and verify all sequences without changing application data."
            ) from error
        print("All PostgreSQL sequences were reset and verified.")
    finally:
        if source_engine is not None:
            source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repair-sequences",
        action="store_true",
        help="reset and verify sequences only; do not import SQLite data",
    )
    arguments = parser.parse_args()
    if arguments.repair_sequences:
        repair_sequences()
    else:
        migrate()
