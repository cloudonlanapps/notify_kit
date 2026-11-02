from pydantic import JsonValue

from app.schemas.api_model import ApiModel


class LinkResponse(ApiModel):
    """Provider linkage; null metadata means no registration exists."""

    provider: str
    template: str
    metadata: dict[str, JsonValue] | None
