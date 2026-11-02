from pydantic import JsonValue

from app.schemas.api_model import ApiModel


class TemplateResponse(ApiModel):
    """Stored template definition and current revision."""

    label: str
    revision: int
    definition: dict[str, JsonValue]
