import asyncio

from notify_kit import (
    ErrorCode,
    NotifyProvider,
    ProviderError,
    ProviderResult,
    ProviderState,
    TemplateCheck,
)


class RecordingProvider(NotifyProvider):
    """Deterministic programmable delivery double; no sockets or external services."""

    def __init__(self):
        self.sent = []
        self.checks = []
        self.outcomes = {}
        self.status_outcomes = {}
        self.template_available = True
        self.require_phone = False
        self.delay = 0
        self.fail_unregister = False
        self.metadata = {}

    def validate_configuration(self):
        pass

    def validate_recipient(self, recipient):
        super().validate_recipient(recipient)
        if self.require_phone and recipient.phone is None:
            raise ProviderError("phone is required", code=ErrorCode.RECIPIENT_INVALID)

    async def register_template(self, *, template, idempotency_key):
        return dict(self.metadata)

    async def check_template(self, *, template, metadata):
        self.checks.append(template.label)
        return TemplateCheck(self.template_available, metadata, "Template disabled")

    async def update_template(self, *, template, metadata, idempotency_key):
        return {"revision": template.revision}

    async def unregister_template(self, *, template, metadata, idempotency_key):
        if self.fail_unregister:
            raise ProviderError(
                "Deletion pending", code=ErrorCode.PROVIDER_ACTION_REQUIRED
            )

    async def prepare(self, *, template, metadata, recipient, facts):
        return {
            "definition": template.definition,
            "facts": facts,
            "username": recipient.username,
        }

    async def send(self, *, recipient, prepared, idempotency_key):
        await asyncio.sleep(self.delay)
        self.sent.append((recipient, prepared, idempotency_key))
        outcome = self.outcomes.get(
            recipient.username,
            ProviderResult(ProviderState.DELIVERED, message_id=idempotency_key),
        )
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def check_delivery(self, *, message_id, idempotency_key):
        return self.status_outcomes.get(
            idempotency_key,
            ProviderResult(ProviderState.UNKNOWN, message_id=message_id),
        )
