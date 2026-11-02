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
async def test_should_submit_and_process_through_cli_without_network(kit):
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
async def test_should_preview_through_cli_without_creating_delivery(kit):
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
async def test_should_return_structured_cli_error_for_missing_provider(kit):
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
