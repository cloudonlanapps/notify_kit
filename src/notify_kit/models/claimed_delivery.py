from dataclasses import dataclass

from notify_kit.models.recipient import Recipient
from notify_kit.types import Payload


@dataclass(frozen=True)
class ClaimedDelivery:
    """Internal execution snapshot returned after claiming a delivery."""

    id: str
    provider: str
    recipient: Recipient
    prepared: Payload
    attempts: int
    lease_token: str
    created_at: float
    message_id: str | None
    reconcile: bool
    previous_status: str
