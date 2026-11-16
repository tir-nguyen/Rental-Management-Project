import logging
from logging.config import fileConfig

from flask import current_app

from alembic import context
from sqlalchemy import create_engine, text

from database_config import get_rental_test_postgresql_uri

config = context.config
fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')

target_url = get_rental_test_postgresql_uri()
config.set_main_option('sqlalchemy.url', target_url.replace('%', '%%'))
target_db = current_app.extensions['migrate'].db


def get_metadata():
    if hasattr(target_db, 'metadatas'):
        return target_db.metadatas[None]
    return target_db.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=get_metadata(), literal_binds=True
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    # this callback is used to prevent an auto-migration from being generated
    # when there are no changes to the schema
    # reference: http://alembic.zzzcomputing.com/en/latest/cookbook.html
    def process_revision_directives(_context, _revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    conf_args = current_app.extensions['migrate'].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    connectable = create_engine(target_url)
    try:
        with connectable.connect() as verification_connection:
            identity = verification_connection.execute(
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
                    "Refusing Alembic operation: connected target must be "
                    "localhost:5432/rental_test using the public schema."
                )

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=get_metadata(),
                **conf_args
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
