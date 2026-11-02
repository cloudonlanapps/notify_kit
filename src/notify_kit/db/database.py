import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event, inspect, select
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import ConnectionPoolEntry

from notify_kit.constants import SQLITE_TIMEOUT_SECONDS
from notify_kit.db.models.schema_state_record import SchemaStateRecord
from notify_kit.db.schema import metadata
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.migrations.constants import SCHEMA_REVISION, SCHEMA_STATE_KEY
from notify_kit.models.error_code import ErrorCode


def _serialize_json(value: object) -> str:
    return json.dumps(value, allow_nan=False)


class Database:
    """Own an async engine and fresh, transaction-scoped sessions per operation."""

    def __init__(self, url: str | URL) -> None:
        """Configure SQLite or PostgreSQL without connecting or reading settings."""
        parsed = make_url(url)
        if parsed.drivername not in {"sqlite+aiosqlite", "postgresql+asyncpg"}:
            raise NotifierError(
                ErrorCode.INVALID_REQUEST, "Use sqlite+aiosqlite or postgresql+asyncpg"
            )
        self.is_sqlite = parsed.get_backend_name() == "sqlite"
        self.engine = create_async_engine(
            parsed,
            echo=False,
            hide_parameters=True,
            json_serializer=_serialize_json,
            connect_args={"timeout": SQLITE_TIMEOUT_SECONDS} if self.is_sqlite else {},
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        if self.is_sqlite:
            event.listen(self.engine.sync_engine, "connect", self._enable_foreign_keys)

    @staticmethod
    def _enable_foreign_keys(
        connection: DBAPIConnection, connection_record: ConnectionPoolEntry
    ) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()

    @asynccontextmanager
    async def session(self, *, write: bool = False) -> AsyncGenerator[AsyncSession]:
        """Commit or roll back internally; serialize SQLite writers before reads."""
        async with self.sessions() as session:
            try:
                if write and self.is_sqlite:
                    connection = await session.connection()
                    await connection.exec_driver_sql("BEGIN IMMEDIATE")
                yield session
                await session.commit()
            except IntegrityError:
                await session.rollback()
                raise
            except SQLAlchemyError:
                await session.rollback()
                raise NotifierError(
                    ErrorCode.STORAGE_ERROR, "Database operation failed"
                ) from None
            except BaseException:
                await session.rollback()
                raise

    async def initialize(self) -> None:
        """Check migration compatibility; schema changes belong to application Alembic."""
        try:
            async with self.engine.begin() as connection:
                await connection.run_sync(self._check_schema)
        except SQLAlchemyError:
            raise NotifierError(
                ErrorCode.STORAGE_ERROR, "Unable to check database schema"
            ) from None

    @staticmethod
    def _check_schema(connection: Connection) -> None:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        for table in metadata().sorted_tables:
            if table.name not in tables:
                raise NotifierError(
                    ErrorCode.SCHEMA_MISMATCH,
                    "notify_kit migrations are required; run the application's Alembic upgrade heads before startup",
                )
            actual = {column["name"] for column in inspector.get_columns(table.name)}
            missing = set(table.columns.keys()) - actual
            if missing:
                raise NotifierError(
                    ErrorCode.SCHEMA_MISMATCH,
                    f"Database requires migration: {table.name} is missing {', '.join(sorted(missing))}. Run application migrations before startup.",
                )

        revision = connection.scalar(
            select(SchemaStateRecord.revision).where(
                SchemaStateRecord.key == SCHEMA_STATE_KEY
            )
        )
        if revision != SCHEMA_REVISION:
            raise NotifierError(
                ErrorCode.SCHEMA_MISMATCH,
                f"Installed notify_kit expects schema {SCHEMA_REVISION}; database reports {revision!r}. Align the package version and application migrations.",
            )

    async def aclose(self) -> None:
        """Dispose the engine and its idle pooled connections."""
        await self.engine.dispose()
