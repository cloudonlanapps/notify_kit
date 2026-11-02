from pydantic import Field

from app.constants import MIN_TEXT_LENGTH
from app.schemas.api_model import ApiModel


class RecipientSchema(ApiModel):
    """A provider destination and optional display name."""

    username: str = Field(min_length=MIN_TEXT_LENGTH)
    name: str | None = None
    email: str | None = None
    phone: str | None = None
