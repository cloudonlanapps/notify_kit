import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from uuid import uuid4

from notify_kit.completion_handler import CompletionHandler
from notify_kit.constants import (
    DEFAULT_WORKER_BATCH_SIZE,
    MIN_WORKER_BATCH_SIZE,
)
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.errors.provider_error import ProviderError
from notify_kit.models.completion_status import CompletionStatus
from notify_kit.models.delivery_state import DeliveryState
from notify_kit.models.delivery_status import DeliveryStatus
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.prepared_delivery import PreparedDelivery
from notify_kit.models.recipient import Recipient
from notify_kit.models.retention_policy import RetentionPolicy
from notify_kit.models.retry_policy import RetryPolicy
from notify_kit.models.send_receipt import SendReceipt
from notify_kit.models.template import Template
from notify_kit.models.template_operation import TemplateOperation
from notify_kit.models.worker_policy import WorkerPolicy
from notify_kit.provider import NotifyProvider
from notify_kit.services.provider_calls import provider_call
from notify_kit.services.serialization import checked_template, snapshot_payload
from notify_kit.services.template_lifecycle import TemplateLifecycle
from notify_kit.services.worker import Worker
from notify_kit.storage.database_storage import DatabaseStorage
from notify_kit.types import Payload


class Notifier:
    """Coordinate registered providers and persistent notification jobs.

    Construct with application-owned provider instances, then await initialize().
    send() queues jobs; run_once() executes a bounded batch of due attempts.
    All processes using a database must register the same stable provider names.
    """

    def __init__(
        self,
        *,
        storage: DatabaseStorage,
        providers: Mapping[str, NotifyProvider],
        retry_policy: RetryPolicy | None = None,
        worker_policy: WorkerPolicy | None = None,
        retention_policy: RetentionPolicy | None = None,
        completion_handler: CompletionHandler | None = None,
    ) -> None:
        """Register configured provider instances and attach persistent storage."""
        self._storage = storage
        self._providers = dict(providers)
        self._worker = Worker(
            storage,
            self._providers,
            retry=retry_policy or RetryPolicy(),
            policy=worker_policy or WorkerPolicy(),
            retention=retention_policy or RetentionPolicy(),
            handler=completion_handler,
        )
        self.templates = storage.templates
        self._template_lifecycle = TemplateLifecycle(storage)
        for name, provider in self._providers.items():
            if not name.strip():
                raise NotifierError(
                    ErrorCode.INVALID_REQUEST, "Provider names must not be empty"
                )
            try:
                provider.validate_configuration()
            except ProviderError as error:
                raise NotifierError(
                    error.code, error.detail, provider=name, operation="configure"
                ) from None
            except Exception:
                raise NotifierError(
                    ErrorCode.PROVIDER_UNEXPECTED_ERROR,
                    "Provider configuration validation failed unexpectedly",
                    provider=name,
                    operation="configure",
                ) from None

    async def initialize(self) -> None:
        """Initialize persistent storage before using the notifier."""
        await self._storage.initialize()

    def _provider(self, name: str) -> NotifyProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise NotifierError(
                ErrorCode.PROVIDER_NOT_REGISTERED,
                f"Provider is not registered: {name}",
                provider=name,
            ) from None

    async def template_register(self, *, provider: str, template: str) -> Payload:
        """Register one of many templates for this provider and persist metadata."""
        result = await self._template_lifecycle.mutate(
            provider, self._provider(provider), template, TemplateOperation.REGISTER
        )
        assert result is not None
        return result

    async def template_update(self, *, provider: str, template: str) -> Payload:
        """Synchronize the current definition using provider-specific version/approval rules."""
        result = await self._template_lifecycle.mutate(
            provider, self._provider(provider), template, TemplateOperation.UPDATE
        )
        assert result is not None
        return result

    async def template_unregister(self, *, provider: str, template: str) -> None:
        """Confirm provider removal before deleting linkage; leave the definition intact."""
        await self._template_lifecycle.mutate(
            provider, self._provider(provider), template, TemplateOperation.UNREGISTER
        )

    async def template_recover(
        self,
        *,
        provider: str,
        template: str,
        operation: TemplateOperation,
        confirmed_stopped: bool,
    ) -> Payload | None:
        """Reconcile the same interrupted mutation using its stable operation key.

        The application must confirm that the original process/call has stopped.
        This is an operator recovery action, not automatic concurrent takeover.
        """
        implementation = self._provider(provider)
        await self._storage.links.release_interrupted(
            template, confirmed_stopped=confirmed_stopped
        )
        return await self._template_lifecycle.mutate(
            provider, implementation, template, operation
        )

    async def template_status(
        self,
        *,
        provider: str,
        template: str,
        refresh: bool = False,
    ) -> Payload | None:
        """Read linkage metadata, optionally refreshing it through the provider.

        None indicates no registration row. Refresh persists returned metadata
        and raises NotifierError if the provider reports an unavailable template.
        """
        implementation = self._provider(provider)
        definition = await self.templates.get(template)
        metadata = await self._storage.links.get(
            provider, template, require_current=refresh
        )
        if metadata is None or not refresh:
            return metadata
        return await self._check_template(
            provider, implementation, definition, metadata
        )

    async def _check_template(
        self,
        name: str,
        provider: NotifyProvider,
        template: Template,
        metadata: Payload,
    ) -> Payload:
        check = await provider_call(
            name,
            "check_template",
            lambda: provider.check_template(template=template, metadata=metadata),
        )
        check = checked_template(check)
        await self._storage.links.save(name, template, check.metadata)
        if not check.available:
            raise NotifierError(
                check.error_code or ErrorCode.TEMPLATE_UNAVAILABLE,
                check.reason or "Template is not available",
                provider=name,
                operation="check_template",
            )
        return check.metadata

    async def send(
        self,
        *,
        provider: str,
        template: str,
        recipients: Sequence[Recipient],
        facts: Payload,
        idempotency_key: str,
    ) -> SendReceipt:
        """Verify linked templates, prepare and atomically queue each recipient.

        Identical replays return existing IDs. Reusing a key for changed inputs
        fails. No linkage means preparation proceeds without a registration check.
        Provider preparation errors become individual failed jobs. Submission
        never delivers messages. No recipient deduplication is performed.
        """
        if not idempotency_key:
            raise NotifierError(
                ErrorCode.INVALID_REQUEST, "idempotency_key must not be empty"
            )
        implementation = self._provider(provider)
        destinations = tuple(recipients)
        try:
            request = json.dumps(
                {
                    "provider": provider,
                    "template": template,
                    "facts": facts,
                    "recipients": [asdict(r) for r in destinations],
                },
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise NotifierError(
                ErrorCode.INVALID_REQUEST,
                "Facts and recipients must contain JSON-compatible values",
            ) from None
        receipt = await self._storage.deliveries.find_request(idempotency_key, request)
        if receipt is not None:
            return receipt
        definition = await self.templates.get(template)
        metadata = await self._storage.links.get(
            provider, template, require_current=True
        )
        if metadata is not None:
            metadata = await self._check_template(
                provider, implementation, definition, metadata
            )
        prepared = await self._prepare(
            provider, implementation, definition, metadata, destinations, facts
        )
        return await self._storage.deliveries.enqueue(
            provider=provider,
            template=template,
            request=request,
            idempotency_key=idempotency_key,
            deliveries=prepared,
            template_revision=definition.revision,
            expected_metadata=metadata,
        )

    async def _prepare(
        self,
        name: str,
        provider: NotifyProvider,
        template: Template,
        metadata: Payload | None,
        recipients: Sequence[Recipient],
        facts: Payload,
    ) -> tuple[PreparedDelivery, ...]:
        prepared: list[PreparedDelivery] = []
        for recipient in recipients:
            delivery_id = uuid4().hex
            try:
                provider.validate_recipient(recipient)
                payload = await provider_call(
                    name,
                    "prepare",
                    lambda: provider.prepare(
                        template=template,
                        metadata=metadata,
                        recipient=recipient,
                        facts=facts,
                    ),
                )
                payload = snapshot_payload(payload)
            except ProviderError as error:
                prepared.append(
                    PreparedDelivery(
                        delivery_id,
                        recipient,
                        {},
                        DeliveryState.FAILED,
                        error.detail,
                        error.code,
                    )
                )
            except NotifierError as error:
                prepared.append(
                    PreparedDelivery(
                        delivery_id,
                        recipient,
                        {},
                        DeliveryState.FAILED,
                        error.detail,
                        error.code,
                    )
                )
            except Exception:
                prepared.append(
                    PreparedDelivery(
                        delivery_id,
                        recipient,
                        {},
                        DeliveryState.FAILED,
                        "Provider preparation failed unexpectedly",
                        ErrorCode.PROVIDER_UNEXPECTED_ERROR,
                    )
                )
            else:
                prepared.append(PreparedDelivery(delivery_id, recipient, payload))
        return tuple(prepared)

    async def get_status(self, delivery_id: str) -> DeliveryStatus:
        """Retrieve a persisted delivery status or raise a not-found NotifierError."""
        return await self._storage.deliveries.get(delivery_id)

    async def get_batch(self, batch_id: str) -> tuple[DeliveryStatus, ...]:
        """Retrieve recipient statuses in submission order or raise a not-found NotifierError."""
        return await self._storage.deliveries.get_batch(batch_id)

    async def run_once(
        self, *, max_jobs: int = DEFAULT_WORKER_BATCH_SIZE
    ) -> tuple[DeliveryStatus, ...]:
        """Run bounded due delivery/status/callback work and retention cleanup."""
        if max_jobs < MIN_WORKER_BATCH_SIZE:
            raise NotifierError(ErrorCode.INVALID_REQUEST, "max_jobs must be positive")
        return await self._worker.run_once(max_jobs)

    async def acknowledge(self, delivery_id: str) -> None:
        """Acknowledge a terminal result after the application commits its own state."""
        await self._storage.deliveries.acknowledge(delivery_id)

    async def get_completion(self, delivery_id: str) -> CompletionStatus:
        """Query callback outcome independently from the notification status."""
        return await self._storage.completions.get(delivery_id)

    async def preview(
        self, *, provider: str, template: str, recipient: Recipient, facts: Payload
    ) -> Payload:
        """Prepare exactly one notification without enqueueing or sending it."""
        implementation = self._provider(provider)
        definition = await self.templates.get(template)
        metadata = await self._storage.links.get(
            provider, template, require_current=True
        )
        if metadata is not None:
            metadata = await self._check_template(
                provider, implementation, definition, metadata
            )
        try:
            implementation.validate_recipient(recipient)
        except ProviderError as error:
            raise NotifierError(
                error.code, error.detail, provider=provider, operation="preview"
            ) from None
        except Exception:
            raise NotifierError(
                ErrorCode.PROVIDER_UNEXPECTED_ERROR,
                "Recipient validation failed unexpectedly",
                provider=provider,
                operation="preview",
            ) from None
        result = await provider_call(
            provider,
            "preview",
            lambda: implementation.prepare(
                template=definition, metadata=metadata, recipient=recipient, facts=facts
            ),
        )

        return snapshot_payload(result)

    async def aclose(self) -> None:
        """Release kit storage resources; provider dependencies remain caller-owned."""
        await self._storage.aclose()
