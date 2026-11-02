from dataclasses import dataclass
from math import isfinite

from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.provider_state import ProviderState


@dataclass(frozen=True)
class ProviderResult:
    """Safe structured outcome returned by a provider."""

    status: ProviderState
    message_id: str | None = None
    reason: str | None = None
    retry_after_seconds: float | None = None
    error_code: ErrorCode | None = None

    def __post_init__(self) -> None:
        """Reject malformed provider retry hints before scheduling persisted work."""
        if self.retry_after_seconds is not None and (
            not isfinite(self.retry_after_seconds) or self.retry_after_seconds < 0
        ):
            raise NotifierError(
                ErrorCode.INVALID_REQUEST,
                "Provider retry delay must be finite and nonnegative",
            )
