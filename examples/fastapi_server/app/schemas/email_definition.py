from pydantic import Field

from app.constants import MIN_TEXT_LENGTH
from app.schemas.api_model import ApiModel


class EmailDefinition(ApiModel):
    """Email content using literal $field substitutions in provider-owned templates."""

    subject: str = Field(min_length=MIN_TEXT_LENGTH)
    text: str = Field(min_length=MIN_TEXT_LENGTH)
    html: str | None = None
