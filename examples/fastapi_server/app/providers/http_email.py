import hashlib
import json
from abc import abstractmethod
from html import escape
from http import HTTPStatus
from math import isfinite

import httpx
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
from pydantic import EmailStr, TypeAdapter, ValidationError

from app.providers.constants import EMAIL_TIMEOUT_SECONDS, MAX_PROVIDER_DETAIL_LENGTH
from app.schemas.email_definition import EmailDefinition
from app.schemas.email_settings import EmailSettings
from app.utils.template_values import substitute, template_values, validate_pattern


class HttpEmailProvider(NotifyProvider):
    """Shared inline-email preparation and single-attempt asynchronous transport.

    Registration validates content and stores its fingerprint in kit metadata;
    it does not create a hosted vendor template. No SDK-global credentials are used.
    """

    def __init__(self, settings: EmailSettings) -> None:
        """Retain explicit configuration; HTTP clients are scoped to each attempt."""
        self._settings = settings

    def validate_configuration(self) -> None:
        """Require a key and valid sender without making any network request."""
        if not self._settings.api_key.get_secret_value().strip():
            raise ProviderError("API key is required")
        if self._settings.from_name and any(
            c in self._settings.from_name for c in "\r\n"
        ):
            raise ProviderError("Sender display name must not contain newlines")

    def validate_recipient(self, recipient: Recipient) -> None:
        """Require an email for this provider while preserving per-recipient failures."""
        super().validate_recipient(recipient)
        if recipient.email is None:
            raise ProviderError(
                "email is required for this provider", code=ErrorCode.RECIPIENT_INVALID
            )
        try:
            TypeAdapter(EmailStr).validate_python(recipient.email)
        except ValidationError:
            raise ProviderError(
                "email is invalid", code=ErrorCode.RECIPIENT_INVALID
            ) from None

    @staticmethod
    def _definition(template: Template) -> EmailDefinition:
        try:
            definition = EmailDefinition.model_validate(template.definition)
        except ValidationError:
            raise ProviderError(
                "Email definition requires subject and text strings, with optional html"
            ) from None
        for pattern in (definition.subject, definition.text, definition.html):
            if pattern is not None:
                validate_pattern(pattern)
        return definition

    async def register_template(
        self, *, template: Template, idempotency_key: str
    ) -> Payload:
        """Validate one of many inline templates and return persisted registration metadata."""
        self._definition(template)
        digest = hashlib.sha256(
            json.dumps(template.definition, sort_keys=True).encode()
        ).hexdigest()
        return {
            "reference": idempotency_key,
            "revision": template.revision,
            "digest": digest,
        }

    async def check_template(
        self, *, template: Template, metadata: Payload
    ) -> TemplateCheck:
        """Verify current content against its stored registration fingerprint."""
        expected = await self.register_template(
            template=template, idempotency_key=str(metadata.get("reference", ""))
        )
        ready = metadata == expected
        return TemplateCheck(
            available=ready,
            metadata=metadata,
            reason=None if ready else "Template changed; update provider registration",
        )

    async def update_template(
        self, *, template: Template, metadata: Payload, idempotency_key: str
    ) -> Payload:
        """Replace inline registration metadata; there is no hosted resource to edit."""
        return await self.register_template(
            template=template, idempotency_key=idempotency_key
        )

    async def unregister_template(
        self, *, template: Template, metadata: Payload, idempotency_key: str
    ) -> None:
        """Confirm removal of metadata-only registration; no vendor deletion is needed."""

    async def prepare(
        self,
        *,
        template: Template,
        metadata: Payload | None,
        recipient: Recipient,
        facts: Payload,
    ) -> Payload:
        """Snapshot personalized subject/text/HTML and sender, excluding credentials."""
        self.validate_recipient(recipient)
        definition = self._definition(template)
        values = template_values(facts, recipient)
        subject = substitute(definition.subject, values)
        if any(c in subject for c in "\r\n"):
            raise ProviderError("Email subject must not contain newlines")
        text = substitute(definition.text, values)
        html = (
            substitute(definition.html, {k: escape(v) for k, v in values.items()})
            if definition.html is not None
            else f"<pre>{escape(text)}</pre>"
        )
        return {
            "subject": subject,
            "text": text,
            "html": html,
            "from_email": str(self._settings.from_email),
            "from_name": self._settings.from_name,
        }

    @abstractmethod
    def endpoint(self) -> str:
        """Return the fixed vendor send endpoint."""

    @abstractmethod
    def headers(self, idempotency_key: str) -> dict[str, str]:
        """Build per-instance authentication and optional request idempotency headers."""

    @abstractmethod
    def payload(
        self, recipient: Recipient, prepared: Payload, idempotency_key: str
    ) -> Payload:
        """Translate the prepared snapshot to the vendor's send payload."""

    @abstractmethod
    def message_id(self, response: dict[str, object]) -> str | None:
        """Read the vendor's message identifier from an accepted response."""

    def _detail(self, response: httpx.Response) -> tuple[str, str | None]:
        try:
            data = response.json()
        except ValueError:
            data = {}
        code = data.get("code", data.get("name")) if isinstance(data, dict) else None
        message = data.get("message") if isinstance(data, dict) else None
        detail = f"HTTP {response.status_code}"
        if isinstance(code, str):
            detail += f" ({code})"
        if isinstance(message, str):
            detail += f": {message}"
        detail = detail.replace(self._settings.api_key.get_secret_value(), "[redacted]")
        return detail[:MAX_PROVIDER_DETAIL_LENGTH], code if isinstance(
            code, str
        ) else None

    async def send(
        self, *, recipient: Recipient, prepared: Payload, idempotency_key: str
    ) -> ProviderResult:
        """Attempt delivery once; classify ambiguous transport outcomes without resending."""
        self.validate_configuration()
        self.validate_recipient(recipient)
        try:
            async with httpx.AsyncClient(
                timeout=EMAIL_TIMEOUT_SECONDS, trust_env=False
            ) as client:
                response = await client.post(
                    self.endpoint(),
                    headers=self.headers(idempotency_key),
                    json=self.payload(recipient, prepared, idempotency_key),
                )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return ProviderResult(
                status=ProviderState.TEMPORARY_FAILURE,
                reason="Could not connect to email provider",
                error_code=ErrorCode.PROVIDER_ERROR,
            )
        except httpx.RequestError:
            return ProviderResult(
                status=ProviderState.UNKNOWN,
                reason="Email request outcome is uncertain",
                error_code=ErrorCode.DELIVERY_UNKNOWN,
            )
        if response.is_success:
            try:
                data = response.json()
                message_id = self.message_id(data) if isinstance(data, dict) else None
            except ValueError:
                message_id = None
            if message_id is None:
                return ProviderResult(
                    status=ProviderState.UNKNOWN,
                    reason="Provider response omitted its message ID",
                    error_code=ErrorCode.DELIVERY_UNKNOWN,
                )
            return ProviderResult(status=ProviderState.ACCEPTED, message_id=message_id)
        reason, code = self._detail(response)
        if (
            response.status_code == HTTPStatus.TOO_MANY_REQUESTS
            or code == "concurrent_idempotent_requests"
        ):
            try:
                retry_after = max(0, float(response.headers.get("retry-after", "0")))
                if not isfinite(retry_after):
                    retry_after = None
            except ValueError:
                retry_after = None
            return ProviderResult(
                status=ProviderState.TEMPORARY_FAILURE,
                reason=reason,
                retry_after_seconds=retry_after,
                error_code=ErrorCode.PROVIDER_ERROR,
            )
        if (
            response.is_server_error
            or response.status_code == HTTPStatus.REQUEST_TIMEOUT
        ):
            return ProviderResult(
                status=ProviderState.UNKNOWN,
                reason=reason,
                error_code=ErrorCode.DELIVERY_UNKNOWN,
            )
        return ProviderResult(
            status=ProviderState.PERMANENT_FAILURE,
            reason=reason,
            error_code=ErrorCode.PROVIDER_ERROR,
        )
