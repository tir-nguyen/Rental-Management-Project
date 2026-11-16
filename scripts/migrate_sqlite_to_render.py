"""Import a verified SQLite snapshot into an explicitly approved Render database."""

import argparse
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, inspect, select, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from database_config import validate_sqlite_source_path
from models import db
from production_database_config import (
    load_production_target,
    validate_connected_target,
)
from scripts.migrate_sqlite_to_postgres import (
    EXPECTED_ALEMBIC_REVISION,
    reset_sequences,
    validate_project_revision,
    validate_source,
)


VERSION_TABLE = "alembic_version"
CHUNK_SIZE = 500


def get_source_snapshot():
    raw_path = os.environ.get("RENTAL_PRODUCTION_SQLITE_SOURCE", "").strip()
    if not raw_path:
        raise ValueError("RENTAL_PRODUCTION_SQLITE_SOURCE is required.")
    source_path = validate_sqlite_source_path(raw_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite migration snapshot not found: {source_path}")
    return source_path


def validate_production_schema(connection):
    validate_project_revision()
    validate_connected_target(
        connection,
        load_production_target(),
    )
    tables = set(inspect(connection).get_table_names(schema="public"))
    expected_tables = set(db.metadata.tables) | {VERSION_TABLE}
    if tables != expected_tables:
        raise RuntimeError(
            "Production schema does not match the reviewed 13-table schema. "
            f"Missing: {sorted(expected_tables - tables)}; "
            f"unexpected: {sorted(tables - expected_tables)}."
        )

    version_table = connection.dialect.identifier_preparer.quote_schema("public")
    revision = connection.execute(
        text(f'SELECT version_num FROM {version_table}."{VERSION_TABLE}"')
    ).scalars().all()
    if revision != [EXPECTED_ALEMBIC_REVISION]:
        raise RuntimeError(
            "Production Alembic revision is not the approved revision "
            f"{EXPECTED_ALEMBIC_REVISION}; found {revision!r}."
        )


def table_row_counts(connection):
    return {
        table.name: connection.execute(
            select(func.count()).select_from(table)
        ).scalar_one()
        for table in db.metadata.sorted_tables
    }


def canonical_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def table_digest(connection, table):
    primary_key = list(table.primary_key.columns)[0]
    digest = hashlib.sha256()
    statement = select(table).order_by(primary_key)
    for row in connection.execute(statement).mappings():
        payload = [
            (column.name, canonical_value(row[column.name]))
            for column in table.columns
        ]
        digest.update(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def preflight(source_path, target):
    validate_project_revision()
    from scripts.migrate_sqlite_to_postgres import create_read_only_source_engine

    source_engine = create_read_only_source_engine(source_path)
    target_engine = create_engine(target.sqlalchemy_url)
    try:
        with source_engine.connect() as source_connection:
            source_connection.exec_driver_sql("BEGIN")
            validate_source(source_connection)
            source_counts = table_row_counts(source_connection)
            source_digests = {
                table.name: table_digest(source_connection, table)
                for table in db.metadata.sorted_tables
            }

        with target_engine.connect() as target_connection:
            validate_production_schema(target_connection)
            target_counts = table_row_counts(target_connection)
            if any(target_counts.values()):
                raise RuntimeError(
                    "Production application tables already contain data; "
                    "refusing to import."
                )
        return source_counts, source_digests
    finally:
        source_engine.dispose()
        target_engine.dispose()


def import_snapshot(source_path, target):
    from scripts.migrate_sqlite_to_postgres import create_read_only_source_engine

    source_engine = create_read_only_source_engine(source_path)
    target_engine = create_engine(target.sqlalchemy_url)
    try:
        with source_engine.connect() as source_connection:
            source_connection.exec_driver_sql("BEGIN")
            validate_source(source_connection)
            source_counts = table_row_counts(source_connection)
            source_digests = {
                table.name: table_digest(source_connection, table)
                for table in db.metadata.sorted_tables
            }

            with target_engine.begin() as target_connection:
                validate_production_schema(target_connection)
                preparer = target_connection.dialect.identifier_preparer
                quoted_tables = ", ".join(
                    f'{preparer.quote_schema("public")}.{preparer.quote(name)}'
                    for name in sorted(db.metadata.tables)
                )
                target_connection.exec_driver_sql(
                    f"LOCK TABLE {quoted_tables} IN ACCESS EXCLUSIVE MODE"
                )
                target_counts = table_row_counts(target_connection)
                if any(target_counts.values()):
                    raise RuntimeError(
                        "Production application tables are not empty; "
                        "refusing to import."
                    )

                imported_counts = {name: 0 for name in source_counts}
                for table in db.metadata.sorted_tables:
                    result = source_connection.execute(select(table))
                    while rows := result.mappings().fetchmany(CHUNK_SIZE):
                        target_connection.execute(
                            table.insert(),
                            [dict(row) for row in rows],
                        )
                        imported_counts[table.name] += len(rows)

                if imported_counts != source_counts:
                    raise RuntimeError(
                        "Imported row counts differ from the source snapshot; "
                        "the transaction will be rolled back."
                    )
                target_digests = {
                    table.name: table_digest(target_connection, table)
                    for table in db.metadata.sorted_tables
                }
                if target_digests != source_digests:
                    raise RuntimeError(
                        "Imported table checksums differ from the source snapshot; "
                        "the transaction will be rolled back."
                    )

        print("Data transaction committed.")
        for name, count in sorted(imported_counts.items()):
            print(f"{name}: {count} row(s)")

        try:
            with target_engine.begin() as connection:
                validate_production_schema(connection)
                reset_sequences(connection, "public")
        except Exception as error:
            raise RuntimeError(
                "Data is committed but sequence reset failed. Do not rerun import. "
                "Stop application writes, resolve the cause, then use the separately "
                "confirmed sequence-repair procedure."
            ) from error

        with target_engine.connect() as connection:
            validate_production_schema(connection)
            final_counts = table_row_counts(connection)
            if final_counts != source_counts:
                raise RuntimeError(
                    "Post-import row counts differ from the source snapshot. "
                    "Keep the application in maintenance mode and investigate."
                )
            final_digests = {
                table.name: table_digest(connection, table)
                for table in db.metadata.sorted_tables
            }
            if final_digests != source_digests:
                raise RuntimeError(
                    "Post-commit table checksums differ from the source snapshot. "
                    "Keep the application in maintenance mode and investigate."
                )
            for table in db.metadata.sorted_tables:
                primary_key = list(table.primary_key.columns)[0]
                maximum_id = connection.execute(
                    select(func.max(primary_key)).select_from(table)
                ).scalar_one()
                sequence_name = connection.execute(
                    text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                    {
                        "table_name": f'"public"."{table.name}"',
                        "column_name": primary_key.name,
                    },
                ).scalar_one()
                sequence_parts = connection.execute(
                    text(
                        "SELECT namespace.nspname, sequence.relname "
                        "FROM pg_class AS sequence "
                        "JOIN pg_namespace AS namespace "
                        "ON namespace.oid = sequence.relnamespace "
                        "WHERE sequence.oid = CAST(:sequence_name AS regclass)"
                    ),
                    {"sequence_name": sequence_name},
                ).one()
                sequence_sql = (
                    f'{connection.dialect.identifier_preparer.quote_schema(sequence_parts.nspname)}.'
                    f'{connection.dialect.identifier_preparer.quote(sequence_parts.relname)}'
                )
                last_value, is_called = connection.execute(
                    text(f"SELECT last_value, is_called FROM {sequence_sql}")
                ).one()
                expected_sequence = (
                    (maximum_id, True) if maximum_id is not None else (1, False)
                )
                if (last_value, is_called) != expected_sequence:
                    raise RuntimeError(
                        f"Sequence verification failed for {table.name}."
                    )
        print("PASS: row counts, table checksums, and PostgreSQL sequences verified.")
    finally:
        source_engine.dispose()
        target_engine.dispose()


def repair_sequences(target):
    engine = create_engine(target.sqlalchemy_url)
    try:
        with engine.begin() as connection:
            validate_production_schema(connection)
            counts = table_row_counts(connection)
            if not any(counts.values()):
                raise RuntimeError(
                    "All production application tables are empty; refusing "
                    "sequence-only repair."
                )
            reset_sequences(connection, "public")
        print(
            "Production sequences were repaired and verified. "
            "No application rows were changed."
        )
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="read-only preflight")
    mode.add_argument("--apply", action="store_true", help="import into an empty production DB")
    mode.add_argument(
        "--repair-sequences",
        action="store_true",
        help="repair sequences only; does not import or alter table rows",
    )
    parser.add_argument("--confirm-target", help="exact approved hostname/database")
    parser.add_argument(
        "--confirm-import",
        help="must be exactly: IMPORT <hostname>/<database>",
    )
    parser.add_argument(
        "--confirm-repair",
        help="must be exactly: REPAIR SEQUENCES <hostname>/<database>",
    )
    args = parser.parse_args()

    target = load_production_target(
        confirmation=args.confirm_target,
        require_confirmation=args.apply or args.repair_sequences,
    )
    if not args.repair_sequences:
        source_path = get_source_snapshot()
    if args.apply and args.confirm_import != f"IMPORT {target.confirmation}":
        raise ValueError(
            "Import requires --confirm-import with the exact text "
            f"'IMPORT {target.confirmation}'."
        )
    if args.repair_sequences:
        if args.confirm_repair != f"REPAIR SEQUENCES {target.confirmation}":
            raise ValueError(
                "Sequence repair requires --confirm-repair with the exact text "
                f"'REPAIR SEQUENCES {target.confirmation}'."
            )
        repair_sequences(target)
        return

    source_counts, source_digests = preflight(source_path, target)
    print(f"Approved target: {target.confirmation}")
    print(f"Read-only source snapshot: {source_path.name}")
    for name, count in sorted(source_counts.items()):
        print(
            f"source {name}: {count} row(s); "
            f"sha256={source_digests[name]}"
        )
    if not args.apply:
        print("Preflight passed; no production data was written.")
        return
    import_snapshot(source_path, target)


if __name__ == "__main__":
    main()
