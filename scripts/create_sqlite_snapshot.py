"""Create a separate, verified SQLite snapshot without modifying its source."""

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from models import db


def create_snapshot(source_path, destination_path, confirmation):
    source = Path(source_path).expanduser().resolve()
    destination = Path(destination_path).expanduser().resolve()

    if confirmation != source.name:
        raise ValueError(
            f"Confirm the source by passing --confirm-source {source.name!r}."
        )
    if source == destination or destination.exists():
        raise ValueError("Snapshot destination must be a different, non-existent file.")
    if PROJECT_ROOT == destination or PROJECT_ROOT in destination.parents:
        raise ValueError("Store the migration snapshot outside the project/Git directory.")
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = source.as_uri() + "?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True)
    destination_connection = None
    destination_created = False
    snapshot_verified = False
    try:
        tables = {
            row[0]
            for row in source_connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        expected = set(db.metadata.tables)
        if tables != expected:
            raise RuntimeError(
                "Source schema does not match the application. "
                f"Missing: {sorted(expected - tables)}; "
                f"unexpected: {sorted(tables - expected)}."
            )
        violations = source_connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"Source contains {len(violations)} foreign-key violation(s)."
            )

        destination_connection = sqlite3.connect(destination)
        destination_created = True
        source_connection.backup(destination_connection)
        destination_connection.close()
        destination_connection = None

        snapshot_connection = sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)
        try:
            snapshot_tables = {
                row[0]
                for row in snapshot_connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if snapshot_tables != expected:
                raise RuntimeError("Snapshot schema did not verify after copying.")
            if snapshot_connection.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Snapshot has a foreign-key violation.")
            counts = {
                table.name: snapshot_connection.execute(
                    f'SELECT count(*) FROM "{table.name}"'
                ).fetchone()[0]
                for table in db.metadata.sorted_tables
            }
            snapshot_verified = True
        finally:
            snapshot_connection.close()
    finally:
        source_connection.close()
        if destination_connection is not None:
            destination_connection.close()
        if destination_created and not snapshot_verified and destination.exists():
            destination.unlink()

    print(f"Snapshot verified: {destination}")
    for table_name, count in sorted(counts.items()):
        print(f"{table_name}: {count} row(s)")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="SQLite source path.")
    parser.add_argument("--destination", required=True, help="New snapshot file path.")
    parser.add_argument(
        "--confirm-source",
        required=True,
        help="Must exactly match the source filename.",
    )
    args = parser.parse_args()
    create_snapshot(args.source, args.destination, args.confirm_source)


if __name__ == "__main__":
    main()
