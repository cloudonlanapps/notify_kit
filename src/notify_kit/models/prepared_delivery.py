from dataclasses import dataclass

from notify_kit.models.delivery_state import DeliveryState
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.recipient import Recipient
from notify_kit.types import Payload


@dataclass(frozen=True)
class PreparedDelivery:
    """Internal delivery snapshot ready for atomic submission."""

    id: str
    recipient: Recipient
    payload: Payload
    status: DeliveryState = DeliveryState.QUEUED
    reason: str | None = None
    error_code: ErrorCode | None = None
