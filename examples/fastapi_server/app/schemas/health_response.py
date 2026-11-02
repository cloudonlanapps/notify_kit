from app.schemas.api_model import ApiModel


class HealthResponse(ApiModel):
    """Server readiness after database initialization."""

    ready: bool
