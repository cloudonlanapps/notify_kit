import asyncio
import logging

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from notify_kit import ErrorCode, Notifier, NotifierError, Recipient


@pytest.mark.requirement("R40")
async def test_should_avoid_write_lock_when_run_once_has_no_due_work(kit):
    notifier, _, path = kit
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        if connection.engine.url.database == str(path):
            statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        assert await notifier.run_once() == ()
        assert statements
        assert not any(
            sql.startswith(("BEGIN IMMEDIATE", "UPDATE", "DELETE", "INSERT"))
            for sql in statements
        )
    finally:
        event.remove(Engine, "before_cursor_execute", record)


@pytest.mark.requirement("R40")
@pytest.mark.parametrize("phase", ["send", "callback"])
async def test_should_finish_only_active_operation_when_stop_is_requested(
    kit, storage, monkeypatch, phase
):
    _, provider, _ = kit
    stop, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    handled = []

    async def handler(event):
        started.set()
        await release.wait()
        handled.append(event.id)

    original = provider.send

    async def blocked_send(**kwargs):
        started.set()
        await release.wait()
        return await original(**kwargs)

    if phase == "send":
        monkeypatch.setattr(provider, "send", blocked_send)
    notifier = Notifier(
        storage=storage,
        providers={"primary": provider},
        completion_handler=handler if phase == "callback" else None,
    )
    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice"), Recipient("bob")],
        facts={},
        idempotency_key="stop",
    )
    task = asyncio.create_task(notifier.run_forever(stop=stop))
    try:
        await asyncio.wait_for(started.wait(), 2)
        stop.set()
        assert not task.done()
        release.set()
        await asyncio.wait_for(task, 2)
        assert task.done()
        if phase == "send":
            assert len(provider.sent) == 1
            statuses = await notifier.get_batch(receipt.batch_id)
            assert sorted(item.status for item in statuses) == ["delivered", "queued"]
        else:
            assert len(handled) == 1
            states = [
                (await notifier.get_completion(item.id)).status
                for item in receipt.deliveries
            ]
            assert sorted(states) == ["handled", "pending"]
    finally:
        stop.set()
        release.set()
        await task


@pytest.mark.requirement("R40")
async def test_should_log_worker_failure_when_example_task_exits_unexpectedly(
    migrated_path, monkeypatch, caplog
):
    from app.main import create_app

    async def crash(self, **kwargs):
        raise NotifierError(ErrorCode.STORAGE_ERROR, "Database operation failed")

    monkeypatch.setattr(Notifier, "run_forever", crash)
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{migrated_path}", registered_providers={}
    )
    observed = False
    with caplog.at_level(logging.ERROR):
        with pytest.raises(NotifierError):
            async with app.router.lifespan_context(app):
                for _ in range(200):
                    if "Notification worker failed" in caplog.text:
                        observed = True
                        break
                    await asyncio.sleep(0.01)
        assert observed, "Worker failure must be logged before shutdown"
