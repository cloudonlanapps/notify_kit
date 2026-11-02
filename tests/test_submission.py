import asyncio

import pytest

from notify_kit import (
    DeliveryState,
    ErrorCode,
    Notifier,
    NotifierError,
    Recipient,
    SQLiteStorage,
)


@pytest.mark.requirement("R29")
async def test_should_commit_individual_ordered_jobs_when_submitting_batch(kit):
    notifier, provider, path = kit
    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice"), Recipient("bob")],
        facts={},
        idempotency_key="batch",
    )
    statuses = await notifier.get_batch(receipt.batch_id)
    assert [d.recipient.username for d in statuses] == ["alice", "bob"]
    assert all(d.status == DeliveryState.QUEUED for d in statuses)
    assert provider.sent == []
    other = Notifier(storage=SQLiteStorage(path), providers={"primary": provider})
    try:
        assert (await other.get_batch(receipt.batch_id)) == statuses
    finally:
        await other.aclose()


@pytest.mark.requirement("R34")
async def test_should_send_every_entry_when_usernames_and_contacts_repeat(kit):
    notifier, provider, _ = kit
    recipients = [
        Recipient("alice", email="same@example.com"),
        Recipient("bob", email="same@example.com"),
        Recipient("alice", email="same@example.com"),
    ]
    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=recipients,
        facts={},
        idempotency_key="duplicates",
    )
    results = await notifier.run_once()
    assert len(results) == len(receipt.deliveries) == len(provider.sent) == 3
    assert len({entry[2] for entry in provider.sent}) == 3


@pytest.mark.requirement("R31")
async def test_should_fail_only_missing_phone_when_batch_contains_valid_recipient(kit):
    notifier, provider, _ = kit
    provider.require_phone = True
    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice", phone="+919876543210"), Recipient("bob")],
        facts={},
        idempotency_key="mixed",
    )
    statuses = await notifier.get_batch(receipt.batch_id)
    assert statuses[1].status == DeliveryState.FAILED
    assert statuses[1].error_code == ErrorCode.RECIPIENT_INVALID
    assert statuses[1].reason == "phone is required"
    assert statuses[1].attempts == 0
    await notifier.run_once()
    assert [entry[0].username for entry in provider.sent] == ["alice"]


@pytest.mark.requirement("R35")
async def test_should_create_no_deliveries_when_recipient_list_is_empty(kit):
    notifier, provider, _ = kit
    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[],
        facts={},
        idempotency_key="empty",
    )
    assert receipt.deliveries == ()
    assert await notifier.run_once() == ()
    assert provider.sent == []


@pytest.mark.requirement("R33")
async def test_should_return_original_ids_when_replaying_identical_request(kit):
    notifier, provider, _ = kit
    request = dict(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice")],
        facts={"amount": 1},
        idempotency_key="replay",
    )
    first = await notifier.send(**request)
    assert await notifier.send(**request) == first
    with pytest.raises(NotifierError) as error:
        await notifier.send(**{**request, "facts": {"amount": 2}})
    assert error.value.code == ErrorCode.IDEMPOTENCY_CONFLICT


@pytest.mark.requirement("R41")
async def test_should_claim_each_job_once_when_two_workers_compete(kit):
    notifier, provider, _ = kit
    provider.delay = 0.01
    await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient(str(i)) for i in range(10)],
        facts={},
        idempotency_key="concurrent",
    )
    await asyncio.gather(notifier.run_once(), notifier.run_once())
    assert len(provider.sent) == 10
    assert len({entry[2] for entry in provider.sent}) == 10


@pytest.mark.requirement("R9")
async def test_should_reject_unknown_provider_before_submission(kit):
    notifier, provider, _ = kit
    with pytest.raises(NotifierError) as error:
        await notifier.send(
            provider="unknown",
            template="receipt",
            recipients=[Recipient("alice")],
            facts={},
            idempotency_key="bad",
        )
    assert error.value.code == ErrorCode.PROVIDER_NOT_REGISTERED
    assert provider.sent == []
