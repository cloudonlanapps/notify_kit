from app.schemas.api_model import ApiModel
from app.schemas.delivery_reference import DeliveryReferenceResponse


class SendResponse(ApiModel):
    """Committed batch ID and ordered per-recipient delivery IDs."""

    batch_id: str
    deliveries: list[DeliveryReferenceResponse]
