from abc import ABC, abstractmethod

from notify_kit.constants import UNSUPPORTED_STATUS_REASON
from notify_kit.errors.provider_error import ProviderError
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.provider_result import ProviderResult
from notify_kit.models.provider_state import ProviderState
from notify_kit.models.recipient import Recipient
from notify_kit.models.template import Template
from notify_kit.models.template_check import TemplateCheck
from notify_kit.types import Payload


class NotifyProvider(ABC):
    """Application-owned provider instance, registered under a stable name.

    The kit neither interprets registration metadata nor distinguishes local
    services from remote services. Implementations must avoid blocking the event
    loop. The application owns and closes any dependencies it injects.
    """

    supports_delivery_status: bool = False

    @abstractmethod
    def validate_configuration(self) -> None:
        """Validate locally; raise ProviderError for invalid configuration."""

    @abstractmethod
    async def register_template(
        self,
        *,
        template: Template,
        idempotency_key: str,
    ) -> Payload:
        """Return opaque linkage metadata; repeated keys must be reconciled.

        Called only on explicit application request. Providers without an external
        registration step can validate the template and return an empty mapping.
        """

    @abstractmethod
    async def check_template(
        self,
        *,
        template: Template,
        metadata: Payload,
    ) -> TemplateCheck:
        """Check a linked template and return refreshed metadata.

        Called only when a linkage row exists, including one with empty metadata.
        Raise ProviderError when availability cannot be determined.
        """

    def validate_recipient(self, recipient: Recipient) -> None:
        """Validate required destination fields before preparation; override as needed."""
        if not recipient.username.strip():
            raise ProviderError(
                "username is required", code=ErrorCode.RECIPIENT_INVALID
            )

    @abstractmethod
    async def prepare(
        self,
        *,
        template: Template,
        metadata: Payload | None,
        recipient: Recipient,
        facts: Payload,
    ) -> Payload:
        """Validate and snapshot a serializable delivery request.

        None means there is no registration row. In that case do not require a
        registration: attempt preparation using the template definition/name.
        Preparation must not deliver the notification.
        """

    @abstractmethod
    async def send(
        self,
        *,
        recipient: Recipient,
        prepared: Payload,
        idempotency_key: str,
    ) -> ProviderResult:
        """Perform one attempt; the kit owns retries.

        Use the stable key to prevent duplicate effects where supported. An
        uncertain outcome must be reported as unknown, not temporary_failure.
        """

    async def update_template(
        self,
        *,
        template: Template,
        metadata: Payload,
        idempotency_key: str,
    ) -> Payload:
        """Update/version an existing registration, or report manual/unsupported action.

        Return opaque metadata even when approval is pending. check_template must
        confirm readiness before sending. Implementations reconcile repeated keys.
        """
        raise ProviderError(
            "Template update is unsupported by this provider",
            code=ErrorCode.UNSUPPORTED_OPERATION,
        )

    async def unregister_template(
        self,
        *,
        template: Template,
        metadata: Payload,
        idempotency_key: str,
    ) -> None:
        """Confirm removal, or raise a safe error; a missing remote template is success.

        Providers with no removal step may return immediately. Providers awaiting
        deletion/manual action must raise rather than prematurely remove linkage.
        """
        raise ProviderError(
            "Template removal is unsupported by this provider",
            code=ErrorCode.UNSUPPORTED_OPERATION,
        )

    async def check_delivery(
        self,
        *,
        message_id: str | None,
        idempotency_key: str,
    ) -> ProviderResult:
        """Optional reconciliation; the default does not authorize a resend."""
        return ProviderResult(
            status=ProviderState.UNKNOWN,
            message_id=message_id,
            reason=UNSUPPORTED_STATUS_REASON,
        )
