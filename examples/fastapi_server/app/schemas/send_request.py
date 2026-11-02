from pydantic import Field, JsonValue

from app.constants import MIN_TEXT_LENGTH
from app.schemas.api_model import ApiModel
from app.schemas.recipient import RecipientSchema


class SendRequest(ApiModel):
    """Persist a batch; delivery happens in a later worker invocation."""

    provider: str = Field(min_length=MIN_TEXT_LENGTH)
    template: str = Field(min_length=MIN_TEXT_LENGTH)
    recipients: list[RecipientSchema]
    facts: dict[str, JsonValue]
    idempotency_key: str = Field(min_length=MIN_TEXT_LENGTH)
