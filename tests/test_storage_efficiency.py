import time

import pytest
from sqlalchemy import event, func, select

from notify_kit.db.database import Database
from notify_kit.db.models.batch_record import BatchRecord
from notify_kit.models.retention_policy import RetentionPolicy
from notify_kit.storage.completion_store import CompletionStore
from notify_kit.storage.job_store import JobStore


@pytest.mark.requirement("R45")
async def test_should_bound_batch_deletion_when_multiple_empty_requests_expire(
    migrated_path,
):
    database = Database(f"sqlite+aiosqlite:///{migrated_path}")
    store = CompletionStore(database)
    try:
        async with database.session(write=True) as session:
            for index in range(5):
                session.add(
                    BatchRecord(
                        id=str(index),
                        idempotency_key=str(index),
                        request="{}",
                        recipient_count=0,
                        created_at=time.time() - 100,
                    )
                )
        await store.cleanup(RetentionPolicy(unacknowledged_seconds=1), max_records=2)
        async with database.session() as session:
            assert (
                await session.scalar(select(func.count()).select_from(BatchRecord)) == 3
            )
    finally:
        await database.aclose()


@pytest.mark.requirement("R45")
async def test_should_avoid_cleanup_and_reporting_writes_when_database_is_idle(
    migrated_path,
):
    database = Database(f"sqlite+aiosqlite:///{migrated_path}")
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database.engine.sync_engine, "before_cursor_execute", record)
    try:
        await JobStore(database).report_missing_providers({"primary"})
        await CompletionStore(database).cleanup(RetentionPolicy())
        assert statements
        assert all(
            not sql.startswith(("BEGIN IMMEDIATE", "UPDATE", "DELETE"))
            for sql in statements
        )
    finally:
        await database.aclose()
