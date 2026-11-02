import json
import logging
from dataclasses import asdict
from string import Template as TextTemplate

from notify_kit import (
    NotifyProvider,
    Payload,
    ProviderError,
    ProviderResult,
    ProviderState,
    Recipient,
    Template,
    TemplateCheck,
)

logger = logging.getLogger("uvicorn.error")


class ConsoleProvider(NotifyProvider):
    """Example application-owned provider; outputs literal text to the server log."""

    def validate_configuration(self) -> None:
        """Console output requires no credentials."""

    @staticmethod
    def _body(template: Template) -> TextTemplate:
        body = template.definition.get("body")
        if not isinstance(body, str):
            raise ProviderError("Console template requires a string body")
        parsed = TextTemplate(body)
        if not parsed.is_valid():
            raise ProviderError(
                "Invalid console placeholder syntax; use $name or ${name}"
            )
        return parsed

    async def register_template(
        self, *, template: Template, idempotency_key: str
    ) -> Payload:
        """Validate content and return metadata that demonstrates revision checking."""
        self._body(template)
        return {"revision": template.revision, "reference": idempotency_key}

    async def check_template(
        self, *, template: Template, metadata: Payload
    ) -> TemplateCheck:
        """A changed definition requires explicitly refreshing its registration."""
        self._body(template)
        available = metadata.get("revision") == template.revision
        return TemplateCheck(
            available=available,
            metadata=metadata,
            reason=None
            if available
            else "Template changed; update this provider registration",
        )

    async def update_template(
        self, *, template: Template, metadata: Payload, idempotency_key: str
    ) -> Payload:
        """Validate the edited definition and replace its provider revision metadata."""
        return await self.register_template(
            template=template, idempotency_key=idempotency_key
        )

    async def unregister_template(
        self, *, template: Template, metadata: Payload, idempotency_key: str
    ) -> None:
        """Console has no external resource to delete, so removal is immediately confirmed."""

    async def prepare(
        self,
        *,
        template: Template,
        metadata: Payload | None,
        recipient: Recipient,
        facts: Payload,
    ) -> Payload:
        """Resolve literal placeholders once; missing registration is permitted."""
        self.validate_recipient(recipient)
        try:
            values = {
                **facts,
                **{
                    key: value
                    for key, value in asdict(recipient).items()
                    if value is not None
                },
            }
            body = self._body(template).substitute(values)
        except KeyError as error:
            raise ProviderError(f"Missing fact: {error.args[0]}") from None
        return {"template": template.label, "body": body}

    async def send(
        self,
        *,
        recipient: Recipient,
        prepared: Payload,
        idempotency_key: str,
    ) -> ProviderResult:
        """Write one notification; delivered means console output, not external delivery."""
        logger.info(
            "Console notification: %s",
            json.dumps(
                {
                    "delivery_id": idempotency_key,
                    "recipient": asdict(recipient),
                    "notification": prepared,
                }
            ),
        )
        return ProviderResult(
            status=ProviderState.DELIVERED, message_id=idempotency_key
        )
