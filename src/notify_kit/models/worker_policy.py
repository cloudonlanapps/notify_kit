from dataclasses import dataclass
from math import isfinite

from notify_kit.constants import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_MAX_AGE_SECONDS,
    DEFAULT_OPERATION_TIMEOUT_SECONDS,
    DEFAULT_POLL_SECONDS,
    DEFAULT_WORKER_BUDGET_SECONDS,
)
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.error_code import ErrorCode


@dataclass(frozen=True)
class WorkerPolicy:
    """Bound delivery age, polling and operation leases in seconds."""

    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
    status_poll_seconds: float = DEFAULT_POLL_SECONDS
    lease_seconds: float = DEFAULT_LEASE_SECONDS
    operation_timeout_seconds: float = DEFAULT_OPERATION_TIMEOUT_SECONDS
    time_budget_seconds: float = DEFAULT_WORKER_BUDGET_SECONDS

    def __post_init__(self) -> None:
        """Require finite positive durations and a lease longer than one operation."""
        values = (
            self.max_age_seconds,
            self.status_poll_seconds,
            self.lease_seconds,
            self.operation_timeout_seconds,
            self.time_budget_seconds,
        )
        if not all(isfinite(value) and value > 0 for value in values):
            raise NotifierError(
                ErrorCode.INVALID_REQUEST,
                "Worker durations must be finite and positive",
            )
        if self.lease_seconds <= self.operation_timeout_seconds:
            raise NotifierError(
                ErrorCode.INVALID_REQUEST, "Lease must exceed operation timeout"
            )
