import time

import pytest

from notify_kit import (
    DeliveryState,
    ErrorCode,
    Notifier,
    NotifierError,
    ProviderResult,
    ProviderState,
    Recipient,
    RetentionPolicy,
    RetryPolicy,
    SQLiteStorage,
)


async def submit(notifier, key="job"):
    return await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice")],
        facts={},
        idempotency_key=key,
    )


@pytest.mark.requirement("R36")
async def test_should_retry_only_transient_failures_until_attempt_limit(
    kit, monkeypatch
):
    notifier, provider, _ = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    notifier._worker.retry = RetryPolicy(max_attempts=2, initial_delay_seconds=5)
    provider.outcomes["alice"] = ProviderResult(
        ProviderState.TEMPORARY_FAILURE, reason="busy"
    )
    receipt = await submit(notifier)
    first = await notifier.run_once()
    assert first[0].status == DeliveryState.RETRY_SCHEDULED
    assert len(provider.sent) == 1
    assert await notifier.run_once() == ()
    clock[0] += 6
    last = await notifier.run_once()
    assert last[0].status == DeliveryState.FAILED
    assert last[0].terminal
    assert last[0].attempts == 2
    assert (await notifier.get_status(receipt.deliveries[0].id)).reason == "busy"


@pytest.mark.requirement("R41")
async def test_should_reconcile_expired_claim_without_resending_after_restart(
    kit, monkeypatch
):
    notifier, provider, path = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    receipt = await submit(notifier)
    claimed = await notifier._storage.deliveries.claim({"primary"}, lease_seconds=1)
    assert claimed is not None
    provider.status_outcomes[claimed.id] = ProviderResult(
        ProviderState.DELIVERED, message_id="remote"
    )
    clock[0] += 2
    other = Notifier(storage=SQLiteStorage(path), providers={"primary": provider})
    try:
        results = await other.run_once()
        assert results[0].status == DeliveryState.DELIVERED
        assert provider.sent == []
        assert (await other.get_status(receipt.deliveries[0].id)).message_id == "remote"
    finally:
        await other.aclose()


@pytest.mark.requirement("R36")
async def test_should_poll_acceptance_then_confirm_delivery_without_resending(
    kit, monkeypatch
):
    notifier, provider, _ = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    provider.supports_delivery_status = True
    provider.outcomes["alice"] = ProviderResult(
        ProviderState.ACCEPTED, message_id="remote"
    )
    receipt = await submit(notifier)
    result = await notifier.run_once()
    assert result[0].status == DeliveryState.ACCEPTED
    assert not result[0].terminal
    provider.status_outcomes[receipt.deliveries[0].id] = ProviderResult(
        ProviderState.DELIVERED, message_id="remote"
    )
    clock[0] += 61
    final = await notifier.run_once()
    assert final[0].status == DeliveryState.DELIVERED
    assert final[0].terminal
    assert len(provider.sent) == 1


@pytest.mark.requirement("R42")
async def test_should_retry_completion_independently_without_redelivering(
    kit, monkeypatch
):
    notifier, provider, path = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    seen = []

    async def handler(event):
        seen.append(event.id)
        if len(seen) == 1:
            raise RuntimeError("application unavailable")

    notifier = Notifier(
        storage=SQLiteStorage(path),
        providers={"primary": provider},
        completion_handler=handler,
    )
    try:
        receipt = await submit(notifier)
        await notifier.run_once()
        assert len(seen) == len(provider.sent) == 1
        clock[0] += 61
        await notifier.run_once()
        assert seen == [seen[0], seen[0]]
        assert len(provider.sent) == 1
        completion = await notifier.get_completion(receipt.deliveries[0].id)
        assert completion.status == "handled"
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R44")
async def test_should_keep_query_separate_from_acknowledgement(kit):
    notifier, _, _ = kit
    receipt = await submit(notifier)
    delivery_id = receipt.deliveries[0].id
    with pytest.raises(NotifierError):
        await notifier.acknowledge(delivery_id)
    await notifier.run_once()
    status = await notifier.get_status(delivery_id)
    assert status.acknowledged_at is None
    await notifier.acknowledge(delivery_id)
    assert (await notifier.get_status(delivery_id)).acknowledged_at is not None


@pytest.mark.requirement("R45")
async def test_should_remove_acknowledged_terminal_records_after_retention(
    kit, monkeypatch
):
    _, provider, path = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    notifier = Notifier(
        storage=SQLiteStorage(path),
        providers={"primary": provider},
        retention_policy=RetentionPolicy(
            acknowledged_seconds=5, unacknowledged_seconds=20
        ),
    )
    try:
        receipt = await submit(notifier)
        await notifier.run_once()
        await notifier.acknowledge(receipt.deliveries[0].id)
        clock[0] += 6
        await notifier.run_once()
        with pytest.raises(NotifierError) as error:
            await notifier.get_status(receipt.deliveries[0].id)
        assert error.value.code == ErrorCode.NOT_FOUND
        with pytest.raises(NotifierError):
            await notifier.get_batch(receipt.batch_id)
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R28")
async def test_should_preview_without_persisting_or_sending(kit):
    notifier, provider, _ = kit
    result = await notifier.preview(
        provider="primary",
        template="receipt",
        recipient=Recipient("alice"),
        facts={"amount": 10},
    )
    assert result["username"] == "alice"
    assert provider.sent == []


@pytest.mark.requirement("R45")
async def test_should_not_return_partial_receipt_or_resend_after_partial_retention(
    kit, monkeypatch
):
    _, provider, path = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    notifier = Notifier(
        storage=SQLiteStorage(path),
        providers={"primary": provider},
        retention_policy=RetentionPolicy(
            acknowledged_seconds=1, unacknowledged_seconds=100
        ),
    )
    request = dict(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice"), Recipient("bob")],
        facts={},
        idempotency_key="partial-retention",
    )
    try:
        receipt = await notifier.send(**request)
        await notifier.run_once()
        await notifier.acknowledge(receipt.deliveries[0].id)
        clock[0] += 2
        await notifier.run_once()
        with pytest.raises(NotifierError) as error:
            await notifier.send(**request)
        assert error.value.code == ErrorCode.IDEMPOTENCY_EXPIRED
        assert len(provider.sent) == 2
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R43")
async def test_should_resume_same_completion_event_after_restart_without_resend(
    kit, monkeypatch
):
    _, provider, path = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    ids = []

    async def unavailable(event):
        ids.append(event.id)
        raise RuntimeError("unavailable")

    first = Notifier(
        storage=SQLiteStorage(path),
        providers={"primary": provider},
        completion_handler=unavailable,
    )
    try:
        receipt = await submit(first)
        await first.run_once()
    finally:
        await first.aclose()

    async def restored(event):
        ids.append(event.id)

    second = Notifier(
        storage=SQLiteStorage(path),
        providers={"primary": provider},
        completion_handler=restored,
    )
    try:
        clock[0] += 61
        await second.run_once()
        assert len(ids) == 2 and ids[0] == ids[1]
        assert len(provider.sent) == 1
        assert (
            await second.get_completion(receipt.deliveries[0].id)
        ).status == "handled"
    finally:
        await second.aclose()


@pytest.mark.requirement("R45")
async def test_should_preserve_pending_callbacks_until_their_deadline(kit, monkeypatch):
    _, provider, path = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])

    async def unavailable(event):
        raise RuntimeError("unavailable")

    notifier = Notifier(
        storage=SQLiteStorage(path),
        providers={"primary": provider},
        completion_handler=unavailable,
        retention_policy=RetentionPolicy(
            acknowledged_seconds=1,
            unacknowledged_seconds=2,
            callback_deadline_seconds=20,
            callback_retry_seconds=60,
        ),
    )
    try:
        receipt = await submit(notifier)
        await notifier.run_once()
        delivery_id = receipt.deliveries[0].id
        await notifier.acknowledge(delivery_id)
        clock[0] += 5
        await notifier.run_once()
        assert (await notifier.get_completion(delivery_id)).status == "pending"
        assert (await notifier.get_status(delivery_id)).terminal
        clock[0] += 20
        await notifier.run_once()
        with pytest.raises(NotifierError):
            await notifier.get_status(delivery_id)
    finally:
        await notifier.aclose()
