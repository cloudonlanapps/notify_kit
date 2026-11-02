from dataclasses import dataclass
from math import isfinite

from notify_kit.constants import (
    DEFAULT_ACKNOWLEDGED_RETENTION_SECONDS,
    DEFAULT_CALLBACK_DEADLINE_SECONDS,
    DEFAULT_CALLBACK_MAX_ATTEMPTS,
    DEFAULT_CALLBACK_RETRY_SECONDS,
    DEFAULT_UNACKNOWLEDGED_RETENTION_SECONDS,
)
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.error_code import ErrorCode


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention and callback deadlines, measured in seconds after completion."""

    acknowledged_seconds: float = DEFAULT_ACKNOWLEDGED_RETENTION_SECONDS
    unacknowledged_seconds: float = DEFAULT_UNACKNOWLEDGED_RETENTION_SECONDS
    callback_deadline_seconds: float = DEFAULT_CALLBACK_DEADLINE_SECONDS
    callback_retry_seconds: float = DEFAULT_CALLBACK_RETRY_SECONDS
    callback_max_attempts: int = DEFAULT_CALLBACK_MAX_ATTEMPTS

    def __post_init__(self) -> None:
        """Reject invalid retention periods and callback policies."""
        values = (
            self.acknowledged_seconds,
            self.unacknowledged_seconds,
            self.callback_deadline_seconds,
            self.callback_retry_seconds,
        )
        if (
            not all(isfinite(value) and value >= 0 for value in values)
            or self.callback_max_attempts < 1
        ):
            raise NotifierError(
                ErrorCode.INVALID_REQUEST, "Invalid retention or callback policy"
            )
