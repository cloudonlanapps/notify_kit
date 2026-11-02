"""Integration tests: invoke explicitly with a disposable PostgreSQL test URL."""

import asyncio
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from notify_kit import DatabaseStorage, DeliveryState, Notifier, Recipient
from notify_kit.db.schema import metadata
from tests.conftest import ROOT
from tests.helpers.recording_provider import RecordingProvider


@pytest.fixture
async def postgres_url():
    raw = os.environ.get("NOTIFY_KIT_TEST_POSTGRES_URL")
    if not raw:
        pytest.fail(
            "Set NOTIFY_KIT_TEST_POSTGRES_URL to a disposable PostgreSQL cluster; these tests create/drop temporary databases"
        )
    base = make_url(raw)
    name = f"notify_test_{uuid4().hex}"
    admin = create_async_engine(base, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name)
    try:
        engine = create_async_engine(url)

        def upgrade(connection):
            config = Config(str(ROOT / "examples/fastapi_server/alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "heads")
            assert (
                compare_metadata(MigrationContext.configure(connection), metadata())
                == []
            )

        try:
            async with engine.begin() as connection:
                await connection.run_sync(upgrade)
        finally:
            await engine.dispose()
        yield url
    finally:
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


@pytest.mark.requirement("R41")
async def test_should_claim_each_recipient_once_when_postgres_workers_compete(
    postgres_url,
):
    provider = RecordingProvider()
    provider.delay = 0.005
    first = Notifier(
        storage=DatabaseStorage(url=postgres_url), providers={"primary": provider}
    )
    second = Notifier(
        storage=DatabaseStorage(url=postgres_url), providers={"primary": provider}
    )
    try:
        await first.initialize()
        await second.initialize()
        await first.templates.create(label="hello", definition={"body": "hello"})
        receipt = await first.send(
            provider="primary",
            template="hello",
            recipients=[Recipient(str(i)) for i in range(20)],
            facts={},
            idempotency_key="batch",
        )
        await asyncio.gather(first.run_once(), second.run_once())
        assert len(provider.sent) == len({entry[2] for entry in provider.sent}) == 20
        assert all(
            d.status == DeliveryState.DELIVERED
            for d in await first.get_batch(receipt.batch_id)
        )
    finally:
        await first.aclose()
        await second.aclose()


@pytest.mark.requirement("R33")
async def test_should_return_same_receipt_when_postgres_submissions_share_request_key(
    postgres_url,
):
    provider = RecordingProvider()
    first = Notifier(
        storage=DatabaseStorage(url=postgres_url), providers={"primary": provider}
    )
    second = Notifier(
        storage=DatabaseStorage(url=postgres_url), providers={"primary": provider}
    )
    try:
        await first.templates.create(label="hello", definition={})
        request = dict(
            provider="primary",
            template="hello",
            recipients=[Recipient("alice")],
            facts={},
            idempotency_key="same",
        )
        results = await asyncio.gather(first.send(**request), second.send(**request))
        assert results[0] == results[1]
        assert len(await first.get_batch(results[0].batch_id)) == 1
    finally:
        await first.aclose()
        await second.aclose()
