"""Small application-configured CLI; migrations remain application-owned."""

import argparse
import asyncio
import importlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from typing import cast

from notify_kit.constants import DEFAULT_WORKER_BATCH_SIZE
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.recipient import Recipient
from notify_kit.notifier import Notifier
from notify_kit.provider import NotifyProvider
from notify_kit.storage.database_storage import DatabaseStorage
from notify_kit.types import Payload


def _providers(spec: str | None) -> dict[str, NotifyProvider]:
    if spec is None:
        return {}
    try:
        module_name, attribute = spec.split(":", 1)
        factory = cast(
            Callable[[], object],
            getattr(importlib.import_module(module_name), attribute),
        )
        value = factory()
        if not isinstance(value, Mapping):
            raise TypeError
        result: dict[str, NotifyProvider] = {}
        for name, provider in cast(Mapping[object, object], value).items():
            if not isinstance(name, str) or not isinstance(provider, NotifyProvider):
                raise TypeError
            result[name] = provider
        return result
    except Exception:
        raise NotifierError(
            ErrorCode.INVALID_REQUEST,
            "Provider factory must be module:callable returning named NotifyProvider instances",
        ) from None


def _object(raw: str) -> Payload:
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return cast(Payload, value)


def _recipient(value: object) -> Recipient:
    if not isinstance(value, dict):
        raise ValueError("Recipient must be a JSON object")
    value = cast(Payload, value)
    username = value.get("username")
    if not isinstance(username, str):
        raise ValueError("Recipient username is required")
    fields: dict[str, str | None] = {}
    for name in ("name", "email", "phone"):
        item = value.get(name)
        if item is not None and not isinstance(item, str):
            raise ValueError("Recipient contact fields must be strings or null")
        fields[name] = item
    return Recipient(username=username, **fields)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Submit, preview and process notify_kit jobs using application providers"
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--factory", help="Application module:callable returning provider instances"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("send", "preview"):
        action = commands.add_parser(name)
        action.add_argument("--provider", required=True)
        action.add_argument("--template", required=True)
        action.add_argument(
            "--facts", default="{}", help="JSON object of template facts"
        )
        if name == "send":
            action.add_argument(
                "--recipients", required=True, help="JSON array of recipients"
            )
            action.add_argument("--idempotency-key", required=True)
        else:
            action.add_argument(
                "--recipient", required=True, help="JSON recipient object"
            )
    worker = commands.add_parser("worker")
    worker.add_argument("--max-jobs", type=int, default=DEFAULT_WORKER_BATCH_SIZE)
    status = commands.add_parser("status")
    status.add_argument("--delivery-id", required=True)
    return parser


async def _run(args: argparse.Namespace) -> object:
    if args.command in ("send", "preview", "worker") and not args.factory:
        raise NotifierError(
            ErrorCode.INVALID_REQUEST,
            "--factory is required for send, preview and worker",
        )
    storage = DatabaseStorage(url=args.database_url)
    try:
        notifier = Notifier(storage=storage, providers=_providers(args.factory))
        await notifier.initialize()
        if args.command == "send":
            values: object = json.loads(args.recipients)
            if not isinstance(values, list):
                raise ValueError("Recipients must be a JSON array")
            recipients = [_recipient(value) for value in cast(list[object], values)]
            receipt = await notifier.send(
                provider=args.provider,
                template=args.template,
                recipients=recipients,
                facts=_object(args.facts),
                idempotency_key=args.idempotency_key,
            )
            return asdict(receipt)
        if args.command == "preview":
            return await notifier.preview(
                provider=args.provider,
                template=args.template,
                recipient=_recipient(_object(args.recipient)),
                facts=_object(args.facts),
            )
        if args.command == "worker":
            return [
                asdict(result)
                for result in await notifier.run_once(max_jobs=args.max_jobs)
            ]
        return asdict(await notifier.get_status(args.delivery_id))
    finally:
        await storage.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    """Return JSON results or structured errors without reading configuration implicitly."""
    args = _parser().parse_args(argv)
    try:
        print(json.dumps(asyncio.run(_run(args)), allow_nan=False))
        return 0
    except NotifierError as error:
        print(
            json.dumps(
                {
                    "code": error.code.value,
                    "detail": error.detail,
                    "provider": error.provider,
                    "operation": error.operation,
                }
            ),
            file=sys.stderr,
        )
    except (ValueError, TypeError):
        print(
            json.dumps(
                {
                    "code": ErrorCode.INVALID_REQUEST,
                    "detail": "Invalid JSON or command arguments",
                }
            ),
            file=sys.stderr,
        )
    return 2
