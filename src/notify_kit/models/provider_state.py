from enum import StrEnum


class ProviderState(StrEnum):
    """Outcome of a single provider operation."""

    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    TEMPORARY_FAILURE = "temporary_failure"
    PERMANENT_FAILURE = "permanent_failure"
    UNKNOWN = "unknown"
