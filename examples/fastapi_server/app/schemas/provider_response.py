from app.schemas.api_model import ApiModel


class ProviderResponse(ApiModel):
    """Public provider identity and configuration validity."""

    name: str
    implementation: str
    configured: bool
    reason: str | None = None
