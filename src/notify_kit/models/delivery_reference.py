from dataclasses import dataclass

from notify_kit.models.recipient import Recipient


@dataclass(frozen=True)
class DeliveryReference:
    """Persistent delivery identifier and its intended recipient."""

    id: str
    recipient: Recipient
