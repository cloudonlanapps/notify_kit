import asyncio
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
    SQLiteStorage,
    WorkerPolicy,
)
from notify_kit.models.template_operation import TemplateOperation


@pytest.mark.requirement("R41")
async def test_should_fence_an_old_worker_after_lease_recovery(kit, monkeypatch):
    notifier, provider, _ = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice")],
        facts={},
        idempotency_key="fence",
    )
    old = await notifier._storage.deliveries.claim({"primary"}, lease_seconds=1)
    clock[0] += 2
    new = await notifier._storage.deliveries.claim({"primary"}, lease_seconds=1)
    assert old.lease_token != new.lease_token
    assert new.reconcile
    assert not await notifier._storage.deliveries.finish(
        old,
        status=DeliveryState.DELIVERED,
        result=ProviderResult(ProviderState.DELIVERED),
        next_attempt_at=None,
        terminal=True,
    )
    assert await notifier._storage.deliveries.finish(
        new,
        status=DeliveryState.DELIVERED,
        result=ProviderResult(ProviderState.DELIVERED),
        next_attempt_at=None,
        terminal=True,
    )
    assert (await notifier.get_completion(new.id)).status == "pending"


@pytest.mark.requirement("R40")
async def test_should_bound_slow_provider_and_preserve_uncertain_outcome(kit):
    _, provider, path = kit
    provider.delay = 10
    notifier = Notifier(
        storage=SQLiteStorage(path),
        providers={"primary": provider},
        worker_policy=WorkerPolicy(
            operation_timeout_seconds=0.01, lease_seconds=1, time_budget_seconds=0.1
        ),
    )
    try:
        receipt = await notifier.send(
            provider="primary",
            template="receipt",
            recipients=[Recipient("alice")],
            facts={},
            idempotency_key="timeout",
        )
        await asyncio.wait_for(notifier.run_once(), timeout=1)
        result = await notifier.get_status(receipt.deliveries[0].id)
        assert result.status == DeliveryState.UNKNOWN
        assert not result.terminal
        assert result.attempts == 1
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R36")
async def test_should_end_uncertain_work_at_maximum_age_without_another_send(
    kit, monkeypatch
):
    _, provider, path = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    notifier = Notifier(
        storage=SQLiteStorage(path),
        providers={"primary": provider},
        worker_policy=WorkerPolicy(max_age_seconds=2, status_poll_seconds=1),
    )
    provider.outcomes["alice"] = ProviderResult(ProviderState.UNKNOWN, reason="timeout")
    try:
        receipt = await notifier.send(
            provider="primary",
            template="receipt",
            recipients=[Recipient("alice")],
            facts={},
            idempotency_key="deadline",
        )
        await notifier.run_once()
        clock[0] += 3
        final = await notifier.run_once()
        assert final[0].terminal
        assert final[0].status == DeliveryState.UNKNOWN
        assert len(provider.sent) == 1
        assert (
            await notifier.get_completion(receipt.deliveries[0].id)
        ).status == "handled"
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R43")
async def test_should_report_callback_exhaustion_without_exposing_exception_or_resending(
    kit, monkeypatch
):
    _, provider, path = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])

    async def handler(event):
        raise RuntimeError("private application state")

    notifier = Notifier(
        storage=SQLiteStorage(path),
        providers={"primary": provider},
        completion_handler=handler,
        retention_policy=RetentionPolicy(callback_max_attempts=1),
    )
    try:
        receipt = await notifier.send(
            provider="primary",
            template="receipt",
            recipients=[Recipient("alice")],
            facts={},
            idempotency_key="callback",
        )
        await notifier.run_once()
        status = await notifier.get_completion(receipt.deliveries[0].id)
        assert status.status == "failed"
        assert "private" not in status.reason
        clock[0] += 100
        await notifier.run_once()
        assert len(provider.sent) == 1
        assert (await notifier.get_completion(receipt.deliveries[0].id)).attempts == 1
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R9")
async def test_should_report_missing_provider_after_restart_without_losing_job(kit):
    notifier, _, path = kit
    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice")],
        facts={},
        idempotency_key="missing-provider",
    )
    restarted = Notifier(storage=SQLiteStorage(path), providers={})
    try:
        await restarted.run_once()
        result = await restarted.get_status(receipt.deliveries[0].id)
        assert result.error_code == ErrorCode.PROVIDER_NOT_REGISTERED
        assert not result.terminal
    finally:
        await restarted.aclose()


@pytest.mark.requirement("R17")
async def test_should_recover_interrupted_template_operation_only_after_explicit_confirmation(
    kit,
):
    notifier, _, _ = kit
    await notifier._storage.links.begin(await notifier.templates.get("receipt"))
    with pytest.raises(NotifierError) as error:
        await notifier.template_recover(
            provider="primary",
            template="receipt",
            operation=TemplateOperation.REGISTER,
            confirmed_stopped=False,
        )
    assert error.value.code == ErrorCode.INVALID_REQUEST
    assert (
        await notifier.template_recover(
            provider="primary",
            template="receipt",
            operation=TemplateOperation.REGISTER,
            confirmed_stopped=True,
        )
        == {}
    )
    assert await notifier.template_status(provider="primary", template="receipt") == {}


@pytest.mark.requirement("R13")
async def test_should_hide_unexpected_provider_exception_per_recipient(kit):
    notifier, provider, _ = kit
    provider.outcomes["alice"] = RuntimeError("SECRET-provider-key")
    await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice"), Recipient("bob")],
        facts={},
        idempotency_key="secret",
    )
    results = await notifier.run_once()
    assert {r.status for r in results} == {
        DeliveryState.UNKNOWN,
        DeliveryState.DELIVERED,
    }
    assert all("SECRET" not in (r.reason or "") for r in results)


@pytest.mark.requirement("R32")
async def test_should_isolate_malformed_provider_result_in_batch(kit):
    notifier, provider, _ = kit
    provider.outcomes["alice"] = None
    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice"), Recipient("bob")],
        facts={},
        idempotency_key="malformed",
    )
    await notifier.run_once()
    statuses = await notifier.get_batch(receipt.batch_id)
    assert statuses[0].status == DeliveryState.UNKNOWN
    assert statuses[1].status == DeliveryState.DELIVERED
