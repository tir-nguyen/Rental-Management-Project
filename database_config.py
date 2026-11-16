"""Database URL selection and normalization."""
import os
from ipaddress import ip_address
from pathlib import Path
import socket
import sys

from sqlalchemy.engine import make_url


LOCAL_TEST_DATABASE = "rental_test"
LOCAL_TEST_PORT = 5432
LOCAL_TEST_HOSTS = {"localhost", "127.0.0.1", "::1"}
PROJECT_ROOT = Path(__file__).resolve().parent
PROTECTED_SQLITE_NAMES = {"rental.db", "rental-before-postgresql.db"}
UNSAFE_CONNECTION_QUERY_KEYS = {
    "dbname",
    "host",
    "hostaddr",
    "options",
    "port",
    "service",
    "servicefile",
    "user",
}


def _normalize_postgresql_url(url):
    if url.drivername in ("postgres", "postgresql", "postgresql+psycopg2"):
        return url.set(drivername="postgresql+psycopg")
    if url.drivername == "postgresql+psycopg":
        return url
    raise ValueError("Database URL must use PostgreSQL with the psycopg driver.")


def get_rental_test_postgresql_uri():
    """Return only the explicitly configured local integration-test database URL."""
    database_url = os.environ.get("RENTAL_TEST_DATABASE_URL", "").strip()
    if not database_url:
        raise ValueError(
            "RENTAL_TEST_DATABASE_URL is required for Alembic and data-migration commands."
        )

    url = _normalize_postgresql_url(make_url(database_url))
    if url.host not in LOCAL_TEST_HOSTS:
        raise ValueError("Test database host must be localhost or a loopback address.")
    if url.port != LOCAL_TEST_PORT:
        raise ValueError(f"Test database port must be {LOCAL_TEST_PORT}.")
    if url.database != LOCAL_TEST_DATABASE:
        raise ValueError(
            f"Test database name must be {LOCAL_TEST_DATABASE!r}; "
            "the PostgreSQL default database is not allowed."
        )
    overridden = UNSAFE_CONNECTION_QUERY_KEYS.intersection(url.query)
    if overridden:
        raise ValueError(
            "Test database URL contains connection overrides that are not allowed: "
            f"{sorted(overridden)}."
        )
    try:
        addresses = {
            ip_address(result[4][0].split("%", 1)[0])
            for result in socket.getaddrinfo(
                url.host, url.port, type=socket.SOCK_STREAM
            )
        }
    except OSError as error:
        raise ValueError("Test database host could not be resolved locally.") from error
    if not addresses or any(not address.is_loopback for address in addresses):
        raise ValueError("Test database host must resolve only to loopback addresses.")

    return url.render_as_string(hide_password=False)


def validate_sqlite_source_path(path):
    source_path = Path(path).expanduser().resolve()
    if source_path.name.casefold() in PROTECTED_SQLITE_NAMES:
        raise ValueError(
            f"Refusing to use protected SQLite database {source_path.name!r} as a test source."
        )
    for protected_name in PROTECTED_SQLITE_NAMES:
        protected_path = PROJECT_ROOT / protected_name
        if (
            source_path.exists()
            and protected_path.exists()
            and os.path.samefile(source_path, protected_path)
        ):
            raise ValueError(
                f"Refusing to use a path that refers to protected database "
                f"{protected_name!r}."
            )
    return source_path


def is_flask_migrate_command(argv=None):
    argv = argv if argv is not None else sys.argv
    return "db" in argv


def is_render_environment():
    return (
        os.environ.get("RENDER", "").strip().lower() == "true"
        or bool(os.environ.get("RENDER_SERVICE_ID", "").strip())
    )


def get_database_uri(base_dir):
    database_url = os.environ.get("DATABASE_URL", "").strip()
    render_environment = is_render_environment()
    if not database_url:
        if render_environment:
            raise RuntimeError(
                "DATABASE_URL is required on Render; configure the PostgreSQL "
                "Internal Database URL for this Web Service."
            )
        return f"sqlite:///{os.path.join(base_dir, 'rental.db')}"

    url = make_url(database_url)
    if url.drivername.startswith("postgresql") or url.drivername == "postgres":
        url = _normalize_postgresql_url(url)
    elif url.drivername != "sqlite":
        raise ValueError("DATABASE_URL must use PostgreSQL or SQLite.")

    if render_environment and not url.drivername.startswith("postgresql"):
        raise ValueError("DATABASE_URL must use PostgreSQL on Render.")

    return url.render_as_string(hide_password=False)
