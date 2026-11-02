from io import StringIO

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from notify_kit import ErrorCode, Notifier, NotifierError, SQLiteStorage
from notify_kit.db.schema import metadata
from notify_kit.migrations.constants import SCHEMA_REVISION
from tests.conftest import ROOT, migrate


@pytest.mark.requirement("R4")
async def test_should_match_orm_schema_when_app_and_kit_migrations_finish(
    migrated_path,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{migrated_path}")

    def compare(connection):
        current = MigrationContext.configure(connection)
        assert set(current.get_current_heads()) == {"app_0001", SCHEMA_REVISION}
        assert compare_metadata(current, metadata()) == []

    try:
        async with engine.connect() as connection:
            await connection.run_sync(compare)
    finally:
        await engine.dispose()


@pytest.mark.requirement("R37")
async def test_should_preserve_jobs_and_mark_historical_events_handled_when_upgrading(
    tmp_path,
):
    path = tmp_path / "old.db"
    await migrate(path, "nk_0001")
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO notify_kit_batches VALUES ('b', 'key', '{}')")
            )
            await connection.execute(
                text(
                    "INSERT INTO notify_kit_deliveries (id,batch_id,position,provider,template_label,username,prepared,status,attempts,created_at,updated_at) VALUES ('d','b',0,'primary','receipt','alice','{}','delivered',1,1,2)"
                )
            )
        await migrate(path)
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT terminal,completed_at FROM notify_kit_deliveries WHERE id='d'"
                    )
                )
            ).one()
            assert tuple(row) == (1, 2)
            assert (
                await connection.execute(
                    text("SELECT delivery_id,status FROM notify_kit_completions")
                )
            ).one() == ("d", "handled")
    finally:
        await engine.dispose()


@pytest.mark.requirement("R4")
def test_should_resolve_packaged_head_when_compiling_postgres_migrations():
    config = Config(
        str(ROOT / "examples/fastapi_server/alembic.ini"), output_buffer=StringIO()
    )
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("notify_kit@head").revision == SCHEMA_REVISION
    config.attributes["database_url"] = (
        "postgresql+asyncpg://unused:unused@localhost/unused"
    )
    command.upgrade(config, "heads", sql=True)
    sql = config.output_buffer.getvalue()
    assert "CREATE TABLE notify_kit_deliveries" in sql
    assert "CREATE TABLE notify_kit_completions" in sql
    assert "nk_0002" in sql


@pytest.mark.requirement("R2")
async def test_should_leave_tables_absent_when_rejecting_unmigrated_database(tmp_path):
    path = tmp_path / "empty.db"
    storage = SQLiteStorage(path)
    try:
        with pytest.raises(NotifierError) as error:
            await storage.initialize()
        assert error.value.code == ErrorCode.SCHEMA_MISMATCH
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        try:
            async with engine.connect() as connection:
                assert (
                    await connection.run_sync(lambda c: inspect(c).get_table_names())
                    == []
                )
        finally:
            await engine.dispose()
    finally:
        await storage.aclose()


@pytest.mark.requirement("R4")
async def test_should_exclude_kit_changes_when_application_autogenerates_migrations(
    migrated_path,
):
    from sqlalchemy import Column, MetaData, Table, Text

    from notify_kit.migrations.integration import exclude_kit_names, exclude_kit_objects

    target = MetaData()
    for table in metadata().sorted_tables:
        table.to_metadata(target)
    target.tables["notify_kit_templates"].append_column(Column("future_field", Text))
    Table("application_items", target, Column("id", Text, primary_key=True))
    engine = create_async_engine(f"sqlite+aiosqlite:///{migrated_path}")

    def compare(connection):
        current = MigrationContext.configure(
            connection,
            opts={
                "include_name": exclude_kit_names,
                "include_object": exclude_kit_objects,
            },
        )
        changes = compare_metadata(current, target)
        assert len(changes) == 1
        assert changes[0][0] == "add_table"
        assert changes[0][1].name == "application_items"

    try:
        async with engine.connect() as connection:
            await connection.run_sync(compare)
    finally:
        await engine.dispose()


@pytest.mark.requirement("R37")
async def test_should_preserve_deliveries_when_worker_schema_is_downgraded_and_upgraded(
    kit,
):
    notifier, _, path = kit
    from notify_kit import Recipient

    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice")],
        facts={},
        idempotency_key="roundtrip",
    )
    await notifier.run_once()
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    def downgrade(connection):
        config = Config(str(ROOT / "examples/fastapi_server/alembic.ini"))
        config.attributes["connection"] = connection
        command.downgrade(config, "nk_0001")
        assert "notify_kit_completions" not in inspect(connection).get_table_names()
        assert (
            connection.scalar(text("SELECT count(*) FROM notify_kit_deliveries")) == 1
        )

    try:
        async with engine.begin() as connection:
            await connection.run_sync(downgrade)
    finally:
        await engine.dispose()
    await migrate(path)
    fresh = Notifier(storage=SQLiteStorage(path), providers={})
    try:
        await fresh.initialize()
        assert (await fresh.get_status(receipt.deliveries[0].id)).status == "delivered"
    finally:
        await fresh.aclose()
