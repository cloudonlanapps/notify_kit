import asyncio
import time
from datetime import datetime

import pytest

from notify_kit import (
    DeliveryState,
    ErrorCode,
    Notifier,
    NotifierError,
    ProviderError,
    ProviderResult,
    ProviderState,
    Recipient,
    RetentionPolicy,
    SQLiteStorage,
    TemplateCheck,
    TemplateOperation,
    WorkerPolicy,
)
from tests.helpers.recording_provider import RecordingProvider


async def submit(notifier, key, recipients=None):
    return await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice")] if recipients is None else recipients,
        facts={},
        idempotency_key=key,
    )


@pytest.mark.requirement("R36")
@pytest.mark.parametrize("lookup_fails", [False, True])
async def test_should_preserve_acceptance_when_status_lookup_is_inconclusive(
    kit, monkeypatch, lookup_fails
):
    notifier, provider, _ = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    provider.supports_delivery_status = True
    provider.outcomes["alice"] = ProviderResult(
        ProviderState.ACCEPTED, message_id="remote"
    )
    receipt = await submit(notifier, "accepted")
    await notifier.run_once()
    if lookup_fails:

        async def unavailable(**kwargs):
            raise RuntimeError("Status API unavailable")

        monkeypatch.setattr(provider, "check_delivery", unavailable)
    clock[0] += 61
    result = await notifier.run_once()
    assert result[0].status == DeliveryState.ACCEPTED
    assert result[0].message_id == "remote"
    assert not result[0].terminal
    clock[0] += 86400
    await notifier.run_once()
    status = await notifier.get_status(receipt.deliveries[0].id)
    assert status.status == DeliveryState.ACCEPTED and status.terminal
    assert len(provider.sent) == 1


@pytest.mark.requirement("R36")
async def test_should_sleep_until_deadline_when_provider_cannot_check_unknown_delivery(
    kit, monkeypatch
):
    notifier, provider, _ = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    provider.outcomes["alice"] = ProviderResult(ProviderState.UNKNOWN)
    receipt = await submit(notifier, "unsupported")
    await notifier.run_once()
    result = await notifier.get_status(receipt.deliveries[0].id)
    assert result.next_attempt_at == result.created_at + 86400
    clock[0] += 61
    assert await notifier.run_once() == ()
    assert len(provider.sent) == 1


@pytest.mark.requirement("R33")
async def test_should_keep_empty_request_receipt_when_cleanup_runs(kit, monkeypatch):
    notifier, _, _ = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    receipt = await submit(notifier, "empty", [])
    await notifier.run_once()
    assert await submit(notifier, "empty", []) == receipt
    clock[0] += 30 * 86400 + 1
    await notifier.run_once()
    assert (await submit(notifier, "empty", [])).batch_id != receipt.batch_id


@pytest.mark.requirement("R14")
@pytest.mark.parametrize("invalid", [float("nan"), datetime(2026, 1, 1), {"set"}])
async def test_should_report_invalid_request_when_template_definition_is_not_json(
    kit, invalid
):
    notifier, _, _ = kit
    for operation in (notifier.templates.create, notifier.templates.update):
        with pytest.raises(NotifierError) as error:
            await operation(label="receipt", definition={"body": invalid})
        assert error.value.code == ErrorCode.INVALID_REQUEST
    assert (await notifier.templates.get("receipt")).revision == 1


@pytest.mark.requirement("R28")
async def test_should_keep_linkage_unchanged_when_preview_refreshes_provider_status(
    kit, monkeypatch
):
    notifier, provider, _ = kit
    await notifier.template_register(provider="primary", template="receipt")

    async def check(**kwargs):
        return TemplateCheck(True, {"checked_at": "new"})

    monkeypatch.setattr(provider, "check_template", check)
    result = await notifier.preview(
        provider="primary",
        template="receipt",
        recipient=Recipient("alice"),
        facts={},
    )
    assert result["username"] == "alice"
    assert await notifier.template_status(provider="primary", template="receipt") == {}


@pytest.mark.requirement("R17")
async def test_should_keep_operation_key_when_another_provider_unregisters(
    kit, monkeypatch
):
    _, primary, path = kit
    other = RecordingProvider()
    notifier = Notifier(
        storage=SQLiteStorage(path), providers={"primary": primary, "other": other}
    )
    keys = []

    async def register(**kwargs):
        keys.append(kwargs["idempotency_key"])
        if len(keys) == 1:
            raise ProviderError("Remote created; response lost")
        return {}

    monkeypatch.setattr(primary, "register_template", register)
    try:
        await notifier.template_register(provider="other", template="receipt")
        with pytest.raises(NotifierError):
            await notifier.template_register(provider="primary", template="receipt")
        await notifier.template_unregister(provider="other", template="receipt")
        await notifier.template_recover(
            provider="primary",
            template="receipt",
            operation=TemplateOperation.REGISTER,
            confirmed_stopped=True,
        )
        assert len(keys) == 2 and keys[0] == keys[1]
        await notifier.template_unregister(provider="primary", template="receipt")
        await notifier.template_register(provider="primary", template="receipt")
        assert keys[2] != keys[1]
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R30")
async def test_should_enqueue_both_requests_when_checks_refresh_opaque_metadata(
    kit, monkeypatch
):
    notifier, provider, _ = kit
    await notifier.template_register(provider="primary", template="receipt")
    waiting, release = asyncio.Event(), asyncio.Event()
    original = provider.prepare
    checks = 0

    async def check(**kwargs):
        nonlocal checks
        checks += 1
        return TemplateCheck(True, {"checked_at": checks})

    async def prepare(**kwargs):
        if checks == 1:
            waiting.set()
            await release.wait()
        return await original(**kwargs)

    monkeypatch.setattr(provider, "check_template", check)
    monkeypatch.setattr(provider, "prepare", prepare)
    first = asyncio.create_task(submit(notifier, "concurrent-one"))
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        second = await submit(notifier, "concurrent-two")
        release.set()
        one = await first
        assert one.batch_id != second.batch_id
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)


@pytest.mark.requirement("R40")
async def test_should_allow_full_timeout_when_claim_and_previous_send_are_slow(
    kit, monkeypatch
):
    _, provider, path = kit
    provider.delay = 0.04
    storage = SQLiteStorage(path)
    notifier = Notifier(
        storage=storage,
        providers={"primary": provider},
        worker_policy=WorkerPolicy(operation_timeout_seconds=0.1, lease_seconds=1),
    )
    original = storage.deliveries.claim

    async def delayed(*args, **kwargs):
        await asyncio.sleep(0.08)
        return await original(*args, **kwargs)

    monkeypatch.setattr(storage.deliveries, "claim", delayed)
    try:
        await submit(notifier, "slow-claim", [Recipient("alice"), Recipient("bob")])
        results = await notifier.run_once()
        assert [item.status for item in results] == [DeliveryState.DELIVERED] * 2
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R43")
async def test_should_dispatch_next_event_when_previous_handler_lease_is_exhausted(
    kit, storage, monkeypatch
):
    _, provider, path = kit
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    policy = RetentionPolicy(callback_max_attempts=1)
    # Create two terminal preparation failures without dispatching their callbacks.
    provider.require_phone = True
    notifier = Notifier(storage=storage, providers={"primary": provider})
    receipt = await submit(
        notifier, "callbacks", [Recipient("alice"), Recipient("bob")]
    )
    first = await storage.completions.claim(lease_seconds=1, policy=policy)
    assert first is not None
    clock[0] += 2
    seen = []

    async def handler(event):
        seen.append(event.id)

    runner = Notifier(
        storage=storage,
        providers={"primary": provider},
        retention_policy=policy,
        completion_handler=handler,
    )
    await runner.run_once()
    assert seen == [receipt.deliveries[1].id]
    assert (await runner.get_completion(receipt.deliveries[0].id)).status == "failed"
    assert (await runner.get_completion(receipt.deliveries[1].id)).status == "handled"


@pytest.mark.requirement("R30")
async def test_should_reject_prepared_snapshot_when_provider_link_is_replaced(
    kit, monkeypatch
):
    notifier, provider, _ = kit
    await notifier.template_register(provider="primary", template="receipt")
    original = provider.prepare

    async def replace(**kwargs):
        await notifier.template_unregister(provider="primary", template="receipt")
        await notifier.template_register(provider="primary", template="receipt")
        return await original(**kwargs)

    monkeypatch.setattr(provider, "prepare", replace)
    with pytest.raises(NotifierError) as error:
        await submit(notifier, "stale")
    assert error.value.code == ErrorCode.TEMPLATE_CHANGED
