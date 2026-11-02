from notify_kit import DeliveryState, ErrorCode

from app.schemas.api_model import ApiModel
from app.schemas.recipient import RecipientSchema


class DeliveryResponse(ApiModel):
    """One recipient delivery status; timestamps are Unix seconds."""

    id: str
    batch_id: str
    provider: str
    template: str
    recipient: RecipientSchema
    status: DeliveryState
    attempts: int
    message_id: str | None
    reason: str | None
    created_at: float
    updated_at: float
    next_attempt_at: float | None
    acknowledged_at: float | None
    error_code: ErrorCode | None = None
    terminal: bool
    completed_at: float | None
