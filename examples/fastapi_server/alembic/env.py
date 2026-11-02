"""Application-owned Alembic environment loading application and kit revisions."""

import asyncio

from alembic import context
from notify_kit.migrations.integration import (
    exclude_kit_names,
    exclude_kit_objects,
    migration_metadata,
)
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.constants import DEFAULT_DATABASE_URL
from app.db.base import ApplicationBase

config = context.config
target_metadata = [ApplicationBase.metadata, migration_metadata()]


def database_url():
    """Use explicit application configuration, never implicit kit settings."""
    return (
        config.attributes.get("database_url")
        or config.get_main_option("sqlalchemy.url")
        or DEFAULT_DATABASE_URL
    )


def configure(**options) -> None:
    """Apply filters to autogeneration only; explicit kit migrations still execute."""
    context.configure(
        target_metadata=target_metadata,
        include_name=exclude_kit_names,
        include_object=exclude_kit_objects,
        compare_type=True,
        **options,
    )


def run_migrations(connection: Connection) -> None:
    """Run both branches on the same connection, transaction and alembic_version table."""
    configure(
        connection=connection, render_as_batch=connection.dialect.name == "sqlite"
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    """Own a temporary migration engine; the application runtime engine is independent."""
    engine = create_async_engine(
        database_url(), poolclass=pool.NullPool, hide_parameters=True
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    configure(
        url=database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    run_migrations(config.attributes["connection"])
else:
    asyncio.run(run_online())
