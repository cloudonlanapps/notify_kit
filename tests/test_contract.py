import asyncio
import inspect

import pytest

from notify_kit import (
    DeliveryState,
    ErrorCode,
    Notifier,
    NotifierError,
    ProviderResult,
    ProviderState,
    Recipient,
    SQLiteStorage,
)
from tests.helpers.recording_provider import RecordingProvider


@pytest.mark.requirement("R1")
async def test_should_accept_opaque_identity_when_no_domain_inputs_are_supplied(kit):
    notifier, _, _ = kit
    assert set(inspect.signature(notifier.send).parameters) == {
        "provider",
        "template",
        "recipients",
        "facts",
        "idempotency_key",
    }
    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("opaque:application:identity")],
        facts={},
        idempotency_key="opaque",
    )
    assert receipt.deliveries[0].recipient.username == "opaque:application:identity"


@pytest.mark.requirement("R3")
async def test_should_avoid_remote_calls_when_constructing_and_validating_notifier(
    kit, monkeypatch
):
    import socket
    from unittest.mock import AsyncMock, Mock

    _, provider, path = kit
    validate = Mock(wraps=provider.validate_configuration)
    monkeypatch.setattr(provider, "validate_configuration", validate)
    network = Mock(side_effect=AssertionError("Construction attempted network access"))
    monkeypatch.setattr(socket, "create_connection", network)
    boundaries = []
    for name in (
        "send",
        "prepare",
        "check_delivery",
        "check_template",
        "register_template",
    ):
        boundary = AsyncMock(
            side_effect=AssertionError("Construction invoked a remote operation")
        )
        monkeypatch.setattr(provider, name, boundary)
        boundaries.append(boundary)
    notifier = Notifier(storage=SQLiteStorage(path), providers={"primary": provider})
    try:
        await notifier.initialize()
        validate.assert_called_once_with()
        network.assert_not_called()
        for boundary in boundaries:
            boundary.assert_not_called()
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R5")
async def test_should_use_registered_instance_when_application_owns_provider(kit):
    notifier, provider, _ = kit
    await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice")],
        facts={"reference": "123"},
        idempotency_key="owned",
    )
    await notifier.run_once()
    assert provider.sent[0][1]["facts"] == {"reference": "123"}


@pytest.mark.requirement("R6")
async def test_should_route_to_named_provider_when_multiple_providers_are_registered(
    kit,
):
    _, _, path = kit
    one, two = RecordingProvider(), RecordingProvider()
    notifier = Notifier(storage=SQLiteStorage(path), providers={"one": one, "two": two})
    try:
        for name in ("one", "two"):
            await notifier.send(
                provider=name,
                template="receipt",
                recipients=[Recipient(name)],
                facts={},
                idempotency_key=name,
            )
        await notifier.run_once()
        assert [entry[0].username for entry in one.sent] == ["one"]
        assert [entry[0].username for entry in two.sent] == ["two"]
    finally:
        await notifier.aclose()


@pytest.mark.requirement("R11")
async def test_should_use_provider_contract_when_delivering_application_module_payload(
    kit,
):
    notifier, provider, _ = kit
    await notifier.templates.update(
        label="receipt", definition={"module": "inapp", "title": "Notice"}
    )
    await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("user-id")],
        facts={},
        idempotency_key="module",
    )
    await notifier.run_once()
    assert provider.sent[0][1]["definition"] == {"module": "inapp", "title": "Notice"}
    assert provider.sent[0][0].username == "user-id"


@pytest.mark.requirement("R12")
async def test_should_isolate_results_when_recipients_have_different_provider_outcomes(
    kit,
):
    notifier, provider, _ = kit
    provider.outcomes = {
        "bad": ProviderResult(ProviderState.PERMANENT_FAILURE, reason="rejected"),
        "uncertain": ProviderResult(ProviderState.UNKNOWN),
    }
    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("ok"), Recipient("bad"), Recipient("uncertain")],
        facts={},
        idempotency_key="outcomes",
    )
    await notifier.run_once()
    statuses = await notifier.get_batch(receipt.batch_id)
    assert [status.status for status in statuses] == [
        DeliveryState.DELIVERED,
        DeliveryState.FAILED,
        DeliveryState.UNKNOWN,
    ]


@pytest.mark.requirement("R14")
async def test_should_keep_templates_when_storage_instance_is_replaced(kit):
    _, provider, path = kit
    restarted = Notifier(storage=SQLiteStorage(path), providers={"primary": provider})
    try:
        await restarted.initialize()
        assert (await restarted.templates.get("receipt")).definition == {
            "body": "Hello $username"
        }
    finally:
        await restarted.aclose()


@pytest.mark.requirement("R21")
async def test_should_preserve_push_payload_when_provider_prepares_application_content(
    kit,
):
    notifier, _, _ = kit
    definition = {"title": "New item", "body": "Message", "data": {"screen": "inbox"}}
    await notifier.templates.update(label="receipt", definition=definition)
    assert (
        await notifier.preview(
            provider="primary",
            template="receipt",
            recipient=Recipient("alice"),
            facts={},
        )
    )["definition"] == definition


@pytest.mark.requirement("R30")
async def test_should_leave_event_loop_available_when_provider_is_awaiting_io(
    kit, monkeypatch
):
    notifier, provider, _ = kit
    started, release = asyncio.Event(), asyncio.Event()
    original = provider.send

    async def suspended(**kwargs):
        started.set()
        await release.wait()
        return await original(**kwargs)

    monkeypatch.setattr(provider, "send", suspended)
    await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice")],
        facts={},
        idempotency_key="async",
    )
    task = asyncio.create_task(notifier.run_once())
    await asyncio.wait_for(started.wait(), timeout=2)
    assert not task.done()
    release.set()
    assert (await task)[0].status == DeliveryState.DELIVERED


@pytest.mark.requirement("R46")
async def test_should_return_not_found_when_delivery_id_is_missing(kit):
    notifier, provider, _ = kit
    with pytest.raises(NotifierError) as error:
        await notifier.get_status("unknown-id")
    assert error.value.code == ErrorCode.NOT_FOUND
    assert "not sent" not in error.value.detail.lower()
    assert provider.sent == []
