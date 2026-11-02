import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from notify_kit import Notifier, SQLiteStorage
from tests.conftest import migrate
from tests.helpers.recording_provider import RecordingProvider


async def legacy_database(path, status):
    await migrate(path, "nk_0001")
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    now = time.time()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO notify_kit_batches VALUES ('b', 'key', '{}')")
            )
            await connection.execute(
                text(
                    "INSERT INTO notify_kit_deliveries "
                    "(id,batch_id,position,provider,template_label,username,prepared,status,attempts,created_at,updated_at) "
                    "VALUES ('d','b',0,'primary','receipt','alice','{}',:status,1,:now,:now)"
                ),
                {"status": status, "now": now},
            )
        await migrate(path)
        async with engine.connect() as connection:
            assert (
                await connection.execute(
                    text("SELECT recipient_count FROM notify_kit_batches WHERE id='b'")
                )
            ).scalar() == 1
    finally:
        await engine.dispose()


@pytest.mark.requirement("R36")
async def test_should_finalize_acceptance_when_migrated_provider_has_no_status_api(
    tmp_path, monkeypatch
):
    path = tmp_path / "accepted.db"
    await legacy_database(path, "accepted")
    provider = RecordingProvider()
    lookup = AsyncMock(side_effect=AssertionError("Unsupported API called"))
    monkeypatch.setattr(provider, "check_delivery", lookup)
    notifier = Notifier(storage=SQLiteStorage(path), providers={"primary": provider})
    try:
        await notifier.initialize()
        await notifier.run_once()
        status = await notifier.get_status("d")
        assert status.status == "accepted" and status.terminal
        lookup.assert_not_called()
        assert provider.sent == []
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R37")
async def test_should_not_replay_historical_callbacks_when_schema_is_upgraded(tmp_path):
    path = tmp_path / "delivered.db"
    await legacy_database(path, "delivered")
    handler = AsyncMock()
    notifier = Notifier(
        storage=SQLiteStorage(path), providers={}, completion_handler=handler
    )
    try:
        await notifier.initialize()
        await notifier.run_once()
        assert (await notifier.get_completion("d")).status == "handled"
        handler.assert_not_called()
    finally:
        await notifier.aclose()
