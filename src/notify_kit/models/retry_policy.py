from dataclasses import dataclass
from math import isfinite

from notify_kit.constants import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_RETRY_DELAY_SECONDS,
    DEFAULT_RETRY_DELAY_SECONDS,
    MIN_ATTEMPTS,
    MIN_DELAY_SECONDS,
)
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.error_code import ErrorCode


@dataclass(frozen=True)
class RetryPolicy:
    """Limits and delays used to schedule temporary-failure retries."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    initial_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS
    max_delay_seconds: float = DEFAULT_MAX_RETRY_DELAY_SECONDS

    def __post_init__(self) -> None:
        """Reject invalid attempt counts and negative delays."""
        if self.max_attempts < MIN_ATTEMPTS:
            raise NotifierError(
                ErrorCode.INVALID_REQUEST, "max_attempts must be positive"
            )
        if (
            not isfinite(self.initial_delay_seconds)
            or not isfinite(self.max_delay_seconds)
            or self.initial_delay_seconds < MIN_DELAY_SECONDS
            or self.max_delay_seconds < MIN_DELAY_SECONDS
        ):
            raise NotifierError(
                ErrorCode.INVALID_REQUEST, "Retry delays must be finite and nonnegative"
            )
