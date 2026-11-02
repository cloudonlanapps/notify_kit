from pydantic import Field, JsonValue

from app.constants import MIN_TEXT_LENGTH
from app.schemas.api_model import ApiModel


class TemplateCreate(ApiModel):
    """Create a uniquely labelled template with provider-owned content."""

    label: str = Field(min_length=MIN_TEXT_LENGTH, pattern=r"^[A-Za-z0-9_.-]+$")
    definition: dict[str, JsonValue]
