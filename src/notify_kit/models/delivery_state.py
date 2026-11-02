from enum import StrEnum


class DeliveryState(StrEnum):
    """Persisted lifecycle of an individual delivery."""

    QUEUED = "queued"
    PROCESSING = "processing"
    RETRY_SCHEDULED = "retry_scheduled"
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"
