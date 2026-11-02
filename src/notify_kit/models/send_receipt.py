from dataclasses import dataclass

from notify_kit.models.delivery_reference import DeliveryReference


@dataclass(frozen=True)
class SendReceipt:
    """Committed batch identifier and ordered recipient references."""

    batch_id: str
    deliveries: tuple[DeliveryReference, ...]
