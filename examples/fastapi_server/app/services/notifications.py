from collections.abc import Mapping

from notify_kit import (
    ErrorCode,
    Notifier,
    NotifierError,
    NotifyProvider,
    ProviderError,
    Recipient,
)

from app.schemas.completion_response import CompletionResponse
from app.schemas.delivery_response import DeliveryResponse
from app.schemas.link_response import LinkResponse
from app.schemas.preview_request import PreviewRequest
from app.schemas.preview_response import PreviewResponse
from app.schemas.provider_response import ProviderResponse
from app.schemas.send_request import SendRequest
from app.schemas.send_response import SendResponse
from app.schemas.template_create import TemplateCreate
from app.schemas.template_recovery import TemplateRecovery
from app.schemas.template_response import TemplateResponse
from app.schemas.template_update import TemplateUpdate


class NotificationService:
    """Adapt the package's public Python API to the example HTTP schemas."""

    def __init__(
        self, notifier: Notifier, providers: Mapping[str, NotifyProvider]
    ) -> None:
        """Retain application-owned provider references without exposing credentials."""
        self._notifier = notifier
        self._providers = dict(providers)

    def providers(self) -> list[ProviderResponse]:
        """List registered providers and their locally validated configuration."""
        return [self.provider(name) for name in self._providers]

    def provider(self, name: str) -> ProviderResponse:
        """Validate configuration without contacting external services."""
        if name not in self._providers:
            raise NotifierError(
                ErrorCode.PROVIDER_NOT_REGISTERED,
                f"Provider is not registered: {name}",
                provider=name,
            )
        provider = self._providers[name]
        try:
            provider.validate_configuration()
        except ProviderError as error:
            return ProviderResponse(
                name=name,
                implementation=type(provider).__name__,
                configured=False,
                reason=str(error),
            )
        return ProviderResponse(
            name=name, implementation=type(provider).__name__, configured=True
        )

    async def create(self, request: TemplateCreate) -> TemplateResponse:
        """Create a local definition; provider registration remains explicit."""
        result = await self._notifier.templates.create(
            label=request.label, definition=request.definition
        )
        return TemplateResponse.model_validate(result)

    async def templates(self) -> list[TemplateResponse]:
        """List definitions ordered by their unique label."""
        return [
            TemplateResponse.model_validate(t)
            for t in await self._notifier.templates.list()
        ]

    async def template(self, label: str) -> TemplateResponse:
        """Read one definition or propagate not-found."""
        return TemplateResponse.model_validate(
            await self._notifier.templates.get(label)
        )

    async def update(self, label: str, request: TemplateUpdate) -> TemplateResponse:
        """Replace content and advance the template revision."""
        return TemplateResponse.model_validate(
            await self._notifier.templates.update(
                label=label, definition=request.definition
            )
        )

    async def delete(self, label: str) -> None:
        """Delete a definition without changing previously queued snapshots."""
        await self._notifier.templates.delete(label)

    async def register(self, provider: str, label: str) -> LinkResponse:
        """Register through the provider and persist returned metadata."""
        self.provider(provider)
        metadata = await self._notifier.template_register(
            provider=provider, template=label
        )
        return LinkResponse(provider=provider, template=label, metadata=metadata)

    async def update_registration(self, provider: str, label: str) -> LinkResponse:
        """Synchronize the current definition with one provider's template."""
        self.provider(provider)
        metadata = await self._notifier.template_update(
            provider=provider, template=label
        )
        return LinkResponse(provider=provider, template=label, metadata=metadata)

    async def unregister(self, provider: str, label: str) -> None:
        """Confirm provider deletion before removing the stored linkage."""
        self.provider(provider)
        await self._notifier.template_unregister(provider=provider, template=label)

    async def registration(
        self, provider: str, label: str, *, refresh: bool = False
    ) -> LinkResponse:
        """Read or refresh linkage; None is distinct from an empty mapping."""
        self.provider(provider)
        metadata = await self._notifier.template_status(
            provider=provider, template=label, refresh=refresh
        )
        return LinkResponse(provider=provider, template=label, metadata=metadata)

    async def send(self, request: SendRequest) -> SendResponse:
        """Submit a durable batch and return identifiers after commit."""
        self.provider(request.provider)
        result = await self._notifier.send(
            provider=request.provider,
            template=request.template,
            facts=request.facts,
            recipients=[Recipient(**r.model_dump()) for r in request.recipients],
            idempotency_key=request.idempotency_key,
        )
        return SendResponse.model_validate(result)

    async def delivery(self, delivery_id: str) -> DeliveryResponse:
        """Read an individual recipient status, including after server restart."""
        return DeliveryResponse.model_validate(
            await self._notifier.get_status(delivery_id)
        )

    async def batch(self, batch_id: str) -> list[DeliveryResponse]:
        """Read every recipient status in submission order."""
        return [
            DeliveryResponse.model_validate(d)
            for d in await self._notifier.get_batch(batch_id)
        ]

    async def run_once(self, max_jobs: int) -> list[DeliveryResponse]:
        """Execute due attempts explicitly; no automatic scheduler runs in the example."""
        return [
            DeliveryResponse.model_validate(d)
            for d in await self._notifier.run_once(max_jobs=max_jobs)
        ]

    async def preview(self, request: PreviewRequest) -> PreviewResponse:
        """Prepare content through the same provider without queueing."""
        payload = await self._notifier.preview(
            provider=request.provider,
            template=request.template,
            recipient=Recipient(**request.recipient.model_dump()),
            facts=request.facts,
        )
        return PreviewResponse(payload=payload)

    async def acknowledge(self, delivery_id: str) -> None:
        """Record application acknowledgement separately from status queries."""
        await self._notifier.acknowledge(delivery_id)

    async def completion(self, delivery_id: str) -> CompletionResponse:
        """Retrieve independently persisted completion handling status."""
        return CompletionResponse.model_validate(
            await self._notifier.get_completion(delivery_id)
        )

    async def recover_template(
        self, provider: str, label: str, request: TemplateRecovery
    ) -> LinkResponse:
        """Explicitly reconcile the same interrupted provider mutation."""
        metadata = await self._notifier.template_recover(
            provider=provider,
            template=label,
            operation=request.operation,
            confirmed_stopped=request.confirmed_stopped,
        )
        return LinkResponse(provider=provider, template=label, metadata=metadata)
