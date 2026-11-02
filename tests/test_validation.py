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
def test_should_reject_policy_when_configuration_is_invalid(construct):
    with pytest.raises(NotifierError) as error:
        construct()
    assert error.value.code == ErrorCode.INVALID_REQUEST


@pytest.mark.requirement("R8")
@pytest.mark.parametrize("value", [math.inf, math.nan])
def test_should_reject_retry_delay_when_value_is_nonfinite(value):
    with pytest.raises(NotifierError):
        RetryPolicy(initial_delay_seconds=value)


@pytest.mark.requirement("R13")
@pytest.mark.parametrize(
    "value", [None, ["not an object"], {"bad": object()}, {"bad": math.nan}]
)
def test_should_reject_provider_payload_when_value_is_not_serializable(value):
    with pytest.raises(NotifierError) as error:
        snapshot_payload(value)
    assert error.value.code == ErrorCode.PROVIDER_ERROR


@pytest.mark.requirement("R8")
async def test_should_reject_configuration_when_names_or_request_keys_are_empty(kit):
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
async def test_should_reject_database_when_schema_is_newer_than_package(migrated_path):
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
async def test_should_emit_completion_without_sending_when_preparation_fails(
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
