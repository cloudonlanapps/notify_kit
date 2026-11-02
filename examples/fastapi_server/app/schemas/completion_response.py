from notify_kit import CompletionState

from app.schemas.api_model import ApiModel


class CompletionResponse(ApiModel):
    """Independent callback status; failure here never resends the notification."""

    id: str
    delivery_id: str
    status: CompletionState
    attempts: int
    reason: str | None
    next_attempt_at: float | None
