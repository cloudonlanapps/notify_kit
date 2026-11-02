from dataclasses import dataclass

from notify_kit.models.delivery_status import DeliveryStatus


@dataclass(frozen=True)
class CompletionEvent:
    """Stable at-least-once event for one recipient's terminal delivery outcome."""

    id: str
    delivery: DeliveryStatus
