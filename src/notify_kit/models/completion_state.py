from enum import StrEnum


class CompletionState(StrEnum):
    """Persisted lifecycle of an independent completion event."""

    PENDING = "pending"
    PROCESSING = "processing"
    HANDLED = "handled"
    FAILED = "failed"
