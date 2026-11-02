from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from notify_kit import Notifier, SQLiteStorage
from tests.helpers.recording_provider import RecordingProvider

ROOT = Path(__file__).resolve().parents[1]


async def migrate(path, revision="heads"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    def run(connection):
        config = Config(str(ROOT / "examples/fastapi_server/alembic.ini"))
        config.attributes["connection"] = connection
        command.upgrade(config, revision)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(run)
    finally:
        await engine.dispose()


@pytest.fixture
async def migrated_path(tmp_path):
    path = tmp_path / "notifications.db"
    await migrate(path)
    return path


@pytest.fixture
async def kit(migrated_path):
    provider = RecordingProvider()
    notifier = Notifier(
        storage=SQLiteStorage(migrated_path), providers={"primary": provider}
    )
    await notifier.initialize()
    await notifier.templates.create(
        label="receipt", definition={"body": "Hello $username"}
    )
    try:
        yield notifier, provider, migrated_path
    finally:
        await notifier.aclose()
