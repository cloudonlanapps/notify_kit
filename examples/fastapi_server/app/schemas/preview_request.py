from pydantic import JsonValue

from app.schemas.api_model import ApiModel
from app.schemas.recipient import RecipientSchema


class PreviewRequest(ApiModel):
    """Prepare one notification without creating a delivery job."""

    provider: str
    template: str
    recipient: RecipientSchema
    facts: dict[str, JsonValue]
