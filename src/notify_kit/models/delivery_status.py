from dataclasses import dataclass

from notify_kit.models.delivery_state import DeliveryState
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.recipient import Recipient


@dataclass(frozen=True)
class DeliveryStatus:
    """Persisted status of one recipient delivery."""

    id: str
    batch_id: str
    provider: str
    template: str
    recipient: Recipient
    status: DeliveryState
    attempts: int
    message_id: str | None
    reason: str | None
    created_at: float
    updated_at: float
    next_attempt_at: float | None
    acknowledged_at: float | None
    error_code: ErrorCode | None = None
    terminal: bool = False
    completed_at: float | None = None
