import math

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from notify_kit import (
    ErrorCode,
    Notifier,
    NotifierError,
    Recipient,
    RetentionPolicy,
    RetryPolicy,
    SQLiteStorage,
    WorkerPolicy,
)
from notify_kit.services.serialization import snapshot_payload


@pytest.mark.requirement("R8")
@pytest.mark.parametrize(
    "construct",
    [
        lambda: RetryPolicy(max_attempts=0),
        lambda: RetryPolicy(initial_delay_seconds=-1),
        lambda: WorkerPolicy(status_poll_seconds=0),
        lambda: WorkerPolicy(lease_seconds=1, operation_timeout_seconds=2),
        lambda: RetentionPolicy(callback_max_attempts=0),
    ],
)
def test_should_reject_invalid_policy_configuration(construct):
    with pytest.raises(NotifierError) as error:
        construct()
    assert error.value.code == ErrorCode.INVALID_REQUEST


@pytest.mark.requirement("R8")
@pytest.mark.parametrize("value", [math.inf, math.nan])
def test_should_reject_nonfinite_retry_delays(value):
    with pytest.raises(NotifierError):
        RetryPolicy(initial_delay_seconds=value)


@pytest.mark.requirement("R13")
@pytest.mark.parametrize(
    "value", [None, ["not an object"], {"bad": object()}, {"bad": math.nan}]
)
def test_should_reject_nonserializable_provider_payload(value):
    with pytest.raises(NotifierError) as error:
        snapshot_payload(value)
    assert error.value.code == ErrorCode.PROVIDER_ERROR


@pytest.mark.requirement("R8")
async def test_should_reject_empty_configuration_names_and_request_keys(kit):
    notifier, provider, path = kit
    with pytest.raises(NotifierError):
        Notifier(storage=SQLiteStorage(path), providers={"": provider})
    with pytest.raises(NotifierError):
        await notifier.send(
            provider="primary",
            template="receipt",
            recipients=[],
            facts={},
            idempotency_key="",
        )
    with pytest.raises(NotifierError):
        await notifier.run_once(max_jobs=0)


@pytest.mark.requirement("R4")
async def test_should_reject_database_newer_than_installed_package(migrated_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{migrated_path}")
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE notify_kit_schema_state SET revision='future'")
        )
    await engine.dispose()
    storage = SQLiteStorage(migrated_path)
    try:
        with pytest.raises(NotifierError) as error:
            await storage.initialize()
        assert error.value.code == ErrorCode.SCHEMA_MISMATCH
    finally:
        await storage.aclose()


@pytest.mark.requirement("R42")
async def test_should_emit_completion_for_preparation_failure_without_provider_send(
    kit,
):
    _, provider, path = kit
    provider.require_phone = True
    events = []

    async def handler(event):
        events.append(event)

    notifier = Notifier(
        storage=SQLiteStorage(path),
        providers={"primary": provider},
        completion_handler=handler,
    )
    try:
        receipt = await notifier.send(
            provider="primary",
            template="receipt",
            recipients=[Recipient("alice")],
            facts={},
            idempotency_key="prep-event",
        )
        await notifier.run_once()
        assert events[0].delivery.id == receipt.deliveries[0].id
        assert events[0].delivery.error_code == ErrorCode.RECIPIENT_INVALID
        assert provider.sent == []
    finally:
        await notifier.aclose()
