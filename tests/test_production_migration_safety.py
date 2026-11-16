import os
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine

from database_config import get_database_uri, validate_sqlite_source_path
from models import db
from production_database_config import load_production_target, redact_url
from scripts.create_sqlite_snapshot import create_snapshot


VALID_PRODUCTION_ENV = {
    "RENTAL_PRODUCTION_DATABASE_URL": (
        "postgresql://migrator:example-secret@db.example.onrender.com:5432/"
        "rental_prod?sslmode=verify-full"
    ),
    "RENTAL_PRODUCTION_EXPECTED_HOST": "db.example.onrender.com",
    "RENTAL_PRODUCTION_EXPECTED_DATABASE": "rental_prod",
    "RENTAL_PRODUCTION_EXPECTED_PORT": "5432",
}


class ProductionTargetSafetyTests(unittest.TestCase):
    def test_requires_production_variables_and_ignores_database_url(self):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "sqlite:///must-not-be-used.db"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "RENTAL_PRODUCTION_DATABASE_URL"):
                load_production_target()

        with patch.dict(
            os.environ,
            {
                **VALID_PRODUCTION_ENV,
                "DATABASE_URL": "sqlite:///must-not-be-used.db",
            },
            clear=True,
        ):
            target = load_production_target()
        self.assertEqual(target.expected_database, "rental_prod")
        self.assertEqual(target.expected_host, "db.example.onrender.com")

    def test_rejects_sqlite_default_database_wrong_host_port_and_tls(self):
        cases = [
            {"RENTAL_PRODUCTION_DATABASE_URL": "sqlite:///rental.db"},
            {
                **VALID_PRODUCTION_ENV,
                "RENTAL_PRODUCTION_DATABASE_URL": (
                    "postgresql://migrator:secret@db.example.onrender.com:5432/"
                    "postgres?sslmode=verify-full"
                ),
            },
            {
                **VALID_PRODUCTION_ENV,
                "RENTAL_PRODUCTION_DATABASE_URL": (
                    "postgresql://migrator:secret@wrong.example:5432/"
                    "rental_prod?sslmode=verify-full"
                ),
            },
            {
                **VALID_PRODUCTION_ENV,
                "RENTAL_PRODUCTION_DATABASE_URL": (
                    "postgresql://migrator:secret@db.example.onrender.com:5433/"
                    "rental_prod?sslmode=verify-full"
                ),
            },
            {
                **VALID_PRODUCTION_ENV,
                "RENTAL_PRODUCTION_DATABASE_URL": (
                    "postgresql://migrator:secret@db.example.onrender.com:5432/"
                    "rental_prod?sslmode=disable"
                ),
            },
            {
                **VALID_PRODUCTION_ENV,
                "RENTAL_PRODUCTION_DATABASE_URL": (
                    "postgresql://migrator:secret@db.example.onrender.com:5432/"
                    "rental_prod?sslmode=prefer"
                ),
            },
            {
                **VALID_PRODUCTION_ENV,
                "RENTAL_PRODUCTION_DATABASE_URL": (
                    "postgresql://migrator:secret@db.example.onrender.com:5432/"
                    "rental_prod"
                ),
            },
        ]
        for environment in cases:
            with self.subTest(environment=environment):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(ValueError):
                        load_production_target()

    def test_accepts_render_tls_modes_without_exposing_credentials(self):
        for sslmode in ("require", "verify-full"):
            environment = {
                **VALID_PRODUCTION_ENV,
                "RENTAL_PRODUCTION_DATABASE_URL": (
                    "postgresql://migrator:example-secret@db.example.onrender.com:5432/"
                    f"rental_prod?sslmode={sslmode}"
                ),
            }
            with self.subTest(sslmode=sslmode):
                with patch.dict(os.environ, environment, clear=True):
                    target = load_production_target()
                self.assertEqual(target.url.query["sslmode"], sslmode)
                self.assertNotIn("example-secret", target.confirmation)
                self.assertNotIn("example-secret", redact_url(target.sqlalchemy_url))

    def test_requires_exact_confirmation_and_rejects_connection_overrides(self):
        with patch.dict(os.environ, VALID_PRODUCTION_ENV, clear=True):
            target = load_production_target()
            with self.assertRaisesRegex(ValueError, "--confirm-target"):
                load_production_target(require_confirmation=True)
            self.assertEqual(
                load_production_target(
                    confirmation=target.confirmation,
                    require_confirmation=True,
                ),
                target,
            )

        with patch.dict(
            os.environ,
            {
                **VALID_PRODUCTION_ENV,
                "RENTAL_PRODUCTION_DATABASE_URL": (
                    "postgresql://migrator:secret@db.example.onrender.com:5432/"
                    "rental_prod?sslmode=verify-full&hostaddr=127.0.0.1"
                ),
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "overrides"):
                load_production_target()


class RuntimeDatabaseConfigurationTests(unittest.TestCase):
    def test_local_without_database_url_keeps_sqlite_default(self):
        with patch.dict(os.environ, {}, clear=True):
            database_url = get_database_uri("D:/project")
        self.assertTrue(database_url.startswith("sqlite:///"))
        self.assertTrue(database_url.endswith("rental.db"))

    def test_render_requires_database_url_and_rejects_sqlite(self):
        with patch.dict(os.environ, {"RENDER": "true"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is required"):
                get_database_uri("D:/project")

        with patch.dict(
            os.environ,
            {
                "RENDER_SERVICE_ID": "srv-example",
                "DATABASE_URL": "sqlite:///rental.db",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "must use PostgreSQL on Render"):
                get_database_uri("D:/project")

    def test_render_normalizes_postgresql_database_url(self):
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "DATABASE_URL": "postgresql://user:secret@db.example:5432/rental",
            },
            clear=True,
        ):
            database_url = get_database_uri("D:/project")
        self.assertTrue(database_url.startswith("postgresql+psycopg://"))


class SqliteSnapshotSafetyTests(unittest.TestCase):
    def test_snapshot_is_separate_and_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "synthetic-source.sqlite"
            destination = temporary / "synthetic-snapshot.sqlite"
            engine = create_engine(f"sqlite+pysqlite:///{source.as_posix()}")
            try:
                db.metadata.create_all(engine)
                with engine.begin() as connection:
                    connection.execute(
                        db.metadata.tables["users"].insert(),
                        {
                            "id": 91,
                            "full_name": "Synthetic fixture",
                            "school_email": "fixture@example.invalid",
                            "phone_number": "0900000091",
                            "password_hash": "synthetic-hash",
                            "created_at": datetime(2026, 1, 2, 3, 4, 5, 123456),
                        },
                    )
            finally:
                engine.dispose()

            original_bytes = source.read_bytes()
            result = create_snapshot(source, destination, source.name)
            self.assertEqual(result, destination.resolve())
            self.assertEqual(source.read_bytes(), original_bytes)

            snapshot = sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)
            try:
                count = snapshot.execute("SELECT count(*) FROM users").fetchone()[0]
                user_id, password_hash = snapshot.execute(
                    "SELECT id, password_hash FROM users"
                ).fetchone()
                tables = {
                    row[0]
                    for row in snapshot.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
            finally:
                snapshot.close()
            self.assertEqual(count, 1)
            self.assertEqual((user_id, password_hash), (91, "synthetic-hash"))
            self.assertEqual(tables, set(db.metadata.tables))

    def test_snapshot_rejects_overwrite_and_repository_destination(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            source = temporary / "fixture.sqlite"
            engine = create_engine(f"sqlite+pysqlite:///{source.as_posix()}")
            try:
                db.metadata.create_all(engine)
            finally:
                engine.dispose()

            existing_destination = temporary / "existing.sqlite"
            existing_destination.write_bytes(b"do not overwrite")
            with self.assertRaisesRegex(ValueError, "non-existent"):
                create_snapshot(source, existing_destination, source.name)

            repository_destination = (
                Path(__file__).resolve().parents[1]
                / f"snapshot-must-not-be-created-{os.getpid()}.sqlite"
            )
            with self.assertRaisesRegex(ValueError, "outside the project"):
                create_snapshot(source, repository_destination, source.name)
            self.assertFalse(repository_destination.exists())

    def test_protected_sqlite_names_are_rejected_as_import_sources(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            for name in ("rental.db", "rental-before-postgresql.db"):
                path = Path(temporary_directory) / name
                path.write_bytes(b"synthetic path guard")
                with self.subTest(name=name):
                    with self.assertRaisesRegex(ValueError, "protected SQLite"):
                        validate_sqlite_source_path(path)


if __name__ == "__main__":
    unittest.main()
