import logging
from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import create_engine, inspect, text

from models import db
from production_database_config import (
    load_production_target,
    validate_connected_target,
)


config = context.config
fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")

if context.is_offline_mode():
    raise RuntimeError("Offline production migrations are disabled.")

confirmation = os.environ.get("RENTAL_PRODUCTION_CONFIRM_TARGET", "")
target = load_production_target(
    confirmation=confirmation,
    require_confirmation=True,
)
config.set_main_option(
    "sqlalchemy.url",
    target.sqlalchemy_url.replace("%", "%%"),
)

engine = create_engine(target.sqlalchemy_url)
try:
    with engine.begin() as connection:
        validate_connected_target(connection, target)
        existing_tables = set(inspect(connection).get_table_names(schema="public"))
        if existing_tables:
            raise RuntimeError(
                "Production schema migration only accepts a blank public schema; "
                f"found {sorted(existing_tables)}."
            )

        context.configure(
            connection=connection,
            target_metadata=db.metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
