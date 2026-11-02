from app.schemas.api_model import ApiModel
from app.schemas.recipient import RecipientSchema


class DeliveryReferenceResponse(ApiModel):
    """Persistent delivery ID and its recipient."""

    id: str
    recipient: RecipientSchema
