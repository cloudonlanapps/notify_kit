import asyncio

import pytest

from notify_kit import DeliveryState, NotifierError, Recipient


async def test_should_process_and_stop_gracefully_when_continuous_worker_is_requested(
    kit,
):
    notifier, provider, _ = kit
    stop = asyncio.Event()
    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient(username="alice")],
        facts={},
        idempotency_key="continuous",
    )
    task = asyncio.create_task(
        notifier.run_forever(stop=stop, poll_interval_seconds=0.01)
    )
    try:
        async with asyncio.timeout(3):
            while True:
                status = await notifier.get_status(receipt.deliveries[0].id)
                if status.status == DeliveryState.DELIVERED:
                    break
                await asyncio.sleep(0.01)
        assert status.status == DeliveryState.DELIVERED
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        assert task.done()
    finally:
        stop.set()
        await task


async def test_should_reject_invalid_interval_when_starting_continuous_worker(kit):
    notifier, _, _ = kit
    with pytest.raises(NotifierError):
        await notifier.run_forever(stop=asyncio.Event(), poll_interval_seconds=0)
