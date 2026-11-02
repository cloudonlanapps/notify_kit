from pydantic import JsonValue

from app.schemas.api_model import ApiModel


class TemplateUpdate(ApiModel):
    """Replace the complete definition without changing its label."""

    definition: dict[str, JsonValue]
