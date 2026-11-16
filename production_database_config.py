"""Fail-closed configuration for explicitly approved production migration tools."""

import os
from dataclasses import dataclass

from sqlalchemy.engine import URL, make_url


ALLOWED_SSL_MODES = {"require", "verify-full"}
BLOCKED_QUERY_KEYS = {
    "dbname",
    "host",
    "hostaddr",
    "options",
    "port",
    "service",
    "servicefile",
    "user",
}


@dataclass(frozen=True)
class ProductionTarget:
    url: URL
    expected_host: str
    expected_database: str
    expected_port: int

    @property
    def confirmation(self):
        return f"{self.expected_host}/{self.expected_database}"

    @property
    def sqlalchemy_url(self):
        return self.url.render_as_string(hide_password=False)


def load_production_target(confirmation=None, require_confirmation=False):
    raw_url = os.environ.get("RENTAL_PRODUCTION_DATABASE_URL", "").strip()
    expected_host = os.environ.get("RENTAL_PRODUCTION_EXPECTED_HOST", "").strip().lower()
    expected_database = os.environ.get(
        "RENTAL_PRODUCTION_EXPECTED_DATABASE", ""
    ).strip()
    raw_port = os.environ.get("RENTAL_PRODUCTION_EXPECTED_PORT", "").strip()

    if not raw_url:
        raise ValueError("RENTAL_PRODUCTION_DATABASE_URL is required.")
    if not expected_host or not expected_database or not raw_port:
        raise ValueError(
            "Set RENTAL_PRODUCTION_EXPECTED_HOST, "
            "RENTAL_PRODUCTION_EXPECTED_DATABASE, and "
            "RENTAL_PRODUCTION_EXPECTED_PORT from Render's database settings."
        )
    try:
        expected_port = int(raw_port)
    except ValueError as error:
        raise ValueError("RENTAL_PRODUCTION_EXPECTED_PORT must be an integer.") from error

    url = make_url(raw_url)
    if url.drivername in ("postgres", "postgresql", "postgresql+psycopg2"):
        url = url.set(drivername="postgresql+psycopg")
    elif url.drivername != "postgresql+psycopg":
        raise ValueError("Production migration target must use PostgreSQL/psycopg.")

    if url.host is None or url.host.lower() != expected_host:
        raise ValueError("Production database URL host does not match the approved host.")
    if url.host.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Production migration URL must not target a local database.")
    if url.port != expected_port:
        raise ValueError("Production database URL port does not match the approved port.")
    if url.database != expected_database or url.database.lower() == "postgres":
        raise ValueError("Production database URL name does not match the approved database.")
    if not url.username or not url.password:
        raise ValueError("Production database URL must contain credentials.")

    blocked_keys = BLOCKED_QUERY_KEYS.intersection(url.query)
    if blocked_keys:
        raise ValueError(
            "Production database URL contains disallowed connection overrides: "
            f"{sorted(blocked_keys)}."
        )
    sslmode = url.query.get("sslmode")
    if sslmode not in ALLOWED_SSL_MODES:
        raise ValueError(
            "Production database URL must require TLS using sslmode=require "
            "or sslmode=verify-full."
        )

    target = ProductionTarget(
        url=url,
        expected_host=expected_host,
        expected_database=expected_database,
        expected_port=expected_port,
    )
    if require_confirmation and confirmation != target.confirmation:
        raise ValueError(
            "Production write requires --confirm-target with the exact "
            f"value {target.confirmation!r}."
        )

    return target


def validate_connected_target(connection, target, require_ssl=True):
    from sqlalchemy import text

    row = connection.execute(
        text(
            "SELECT current_database(), current_user, inet_server_port(), "
            "current_schema(), "
            "EXISTS (SELECT 1 FROM pg_stat_ssl WHERE pid = pg_backend_pid())"
        )
    ).one()
    database, user, port, schema, ssl_enabled = row
    if database != target.expected_database:
        raise RuntimeError("Connected PostgreSQL database name did not match the approval.")
    if user != target.url.username:
        raise RuntimeError("Connected PostgreSQL role did not match the approved URL.")
    if port != target.expected_port:
        raise RuntimeError("Connected PostgreSQL port did not match the approval.")
    if schema != "public":
        raise RuntimeError("Production migration only supports the public schema.")
    if require_ssl and not ssl_enabled:
        raise RuntimeError("Production PostgreSQL connection is not using TLS.")


def redact_url(url):
    return make_url(url).render_as_string(hide_password=True)
