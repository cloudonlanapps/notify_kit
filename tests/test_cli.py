import asyncio
import json
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import pytest

from notify_kit.cli import main


async def cli(path, *arguments):
    args = [
        "--database-url",
        f"sqlite+aiosqlite:///{path}",
        "--factory",
        "tests.helpers.factory:providers",
        *arguments,
    ]
    stdout, stderr = StringIO(), StringIO()

    def run():
        with redirect_stdout(stdout), redirect_stderr(stderr):
            return main(args)

    code = await asyncio.to_thread(run)
    return subprocess.CompletedProcess(args, code, stdout.getvalue(), stderr.getvalue())


@pytest.mark.requirement("R38")
async def test_should_submit_and_process_without_network_when_cli_is_used(kit):
    notifier, _, path = kit
    result = await cli(
        path,
        "send",
        "--provider",
        "primary",
        "--template",
        "receipt",
        "--recipients",
        '[{"username":"alice"}]',
        "--facts",
        "{}",
        "--idempotency-key",
        "cli",
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    queued = await notifier.get_status(receipt["deliveries"][0]["id"])
    assert queued.status == "queued"
    worker = await cli(path, "worker", "--max-jobs", "10")
    assert worker.returncode == 0, worker.stderr
    assert json.loads(worker.stdout)[0]["status"] == "delivered"


@pytest.mark.requirement("R39")
async def test_should_avoid_creating_delivery_when_cli_preview_is_requested(kit):
    _, _, path = kit
    result = await cli(
        path,
        "preview",
        "--provider",
        "primary",
        "--template",
        "receipt",
        "--recipient",
        '{"username":"alice"}',
        "--facts",
        '{"value":"literal"}',
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["facts"] == {"value": "literal"}


@pytest.mark.requirement("R38")
async def test_should_return_structured_cli_error_when_provider_is_missing(kit):
    _, _, path = kit
    result = await cli(
        path,
        "send",
        "--provider",
        "unknown",
        "--template",
        "receipt",
        "--recipients",
        '[{"username":"alice"}]',
        "--facts",
        "{}",
        "--idempotency-key",
        "bad",
    )
    assert result.returncode != 0
    assert json.loads(result.stderr)["code"] == "provider_not_registered"


@pytest.mark.requirement("R38")
async def test_should_leave_jobs_unchanged_when_worker_cli_has_no_factory(kit):
    notifier, _, path = kit
    from notify_kit import Recipient

    receipt = await notifier.send(
        provider="primary",
        template="receipt",
        recipients=[Recipient("alice")],
        facts={},
        idempotency_key="no-factory",
    )
    stderr = StringIO()

    def run():
        with redirect_stderr(stderr):
            return main(["--database-url", f"sqlite+aiosqlite:///{path}", "worker"])

    assert await asyncio.to_thread(run) == 2
    assert json.loads(stderr.getvalue())["code"] == "invalid_request"
    status = await notifier.get_status(receipt.deliveries[0].id)
    assert status.status == "queued" and status.error_code is None
