from app.schemas.api_model import ApiModel


class ErrorResponse(ApiModel):
    """Stable error code and safe application-facing description."""

    code: str
    detail: str
    provider: str | None = None
    operation: str | None = None
