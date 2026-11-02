import hashlib
import json
import logging
import re

from notify_kit import (
    ErrorCode,
    NotifyProvider,
    Payload,
    ProviderError,
    ProviderResult,
    ProviderState,
    Recipient,
    Template,
    TemplateCheck,
)

from app.providers.constants import PHONE_PATTERN
from app.utils.template_values import substitute, template_values, validate_pattern

logger = logging.getLogger("uvicorn.error")


class FakeSmsProvider(NotifyProvider):
    """Registered SMS templates backed by kit metadata; delivery prints to console.

    This is an example provider, not an Indian DLT registration implementation.
    Persisted metadata is its internal template registry, so restarts retain it.
    """

    def validate_configuration(self) -> None:
        """No external credentials are needed."""

    def validate_recipient(self, recipient: Recipient) -> None:
        """Require username and an international phone number for this provider."""
        super().validate_recipient(recipient)
        if recipient.phone is None:
            raise ProviderError(
                "phone is required for this provider", code=ErrorCode.RECIPIENT_INVALID
            )
        if re.fullmatch(PHONE_PATTERN, recipient.phone) is None:
            raise ProviderError(
                "phone must be in international form, for example +919876543210",
                code=ErrorCode.RECIPIENT_INVALID,
            )

    @staticmethod
    def _body(template: Template) -> str:
        body = template.definition.get("body")
        if not isinstance(body, str) or not body:
            raise ProviderError("SMS template requires a non-empty body string")
        validate_pattern(body)
        return body

    async def register_template(
        self, *, template: Template, idempotency_key: str
    ) -> Payload:
        """Return the internal registry entry to persist in the kit's linkage table."""
        body = self._body(template)
        return {
            "template_id": idempotency_key,
            "revision": template.revision,
            "body": body,
            "digest": hashlib.sha256(body.encode()).hexdigest(),
        }

    async def check_template(
        self, *, template: Template, metadata: Payload
    ) -> TemplateCheck:
        """Confirm that the stored internal registration matches the current definition."""
        reference = metadata.get("template_id")
        if not isinstance(reference, str) or not reference:
            return TemplateCheck(
                available=False,
                metadata=metadata,
                reason="SMS template registration is invalid",
            )
        expected = await self.register_template(
            template=template, idempotency_key=reference
        )
        return TemplateCheck(
            available=metadata == expected,
            metadata=metadata,
            reason=None
            if metadata == expected
            else "SMS template changed; update its registration",
        )

    async def update_template(
        self, *, template: Template, metadata: Payload, idempotency_key: str
    ) -> Payload:
        """Replace the internal registered content and revision."""
        return await self.register_template(
            template=template, idempotency_key=idempotency_key
        )

    async def unregister_template(
        self, *, template: Template, metadata: Payload, idempotency_key: str
    ) -> None:
        """Confirm removal; the kit then deletes the persisted registry entry."""

    async def prepare(
        self,
        *,
        template: Template,
        metadata: Payload | None,
        recipient: Recipient,
        facts: Payload,
    ) -> Payload:
        """Require registration and snapshot each recipient's personalized SMS."""
        self.validate_recipient(recipient)
        if metadata is None:
            raise ProviderError(
                "Register this SMS template before sending",
                code=ErrorCode.TEMPLATE_NOT_REGISTERED,
            )
        checked = await self.check_template(template=template, metadata=metadata)
        if not checked.available:
            raise ProviderError(
                checked.reason or "SMS template unavailable",
                code=ErrorCode.TEMPLATE_UNAVAILABLE,
            )
        return {
            "body": substitute(self._body(template), template_values(facts, recipient)),
            "template_id": metadata["template_id"],
        }

    async def send(
        self, *, recipient: Recipient, prepared: Payload, idempotency_key: str
    ) -> ProviderResult:
        """Print SMS:sendto:<phone>:<JSON-quoted message>, without an external request."""
        self.validate_recipient(recipient)
        logger.info(
            "SMS:sendto:%s:%s",
            recipient.phone,
            json.dumps(prepared["body"], ensure_ascii=False),
        )
        return ProviderResult(
            status=ProviderState.DELIVERED, message_id=f"sms-{idempotency_key}"
        )
