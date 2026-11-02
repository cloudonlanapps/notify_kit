from pydantic import JsonValue

from app.schemas.api_model import ApiModel


class PreviewResponse(ApiModel):
    """Provider-specific prepared content for inspection."""

    payload: dict[str, JsonValue]
