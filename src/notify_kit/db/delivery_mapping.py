"""Pure conversions shared by storage transactions."""

from notify_kit.db.models.delivery_record import DeliveryRecord
from notify_kit.models.delivery_state import DeliveryState
from notify_kit.models.delivery_status import DeliveryStatus
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.recipient import Recipient


def delivery_recipient(row: DeliveryRecord) -> Recipient:
    """Build the recipient from its persisted delivery snapshot."""
    return Recipient(
        username=row.username, name=row.display_name, email=row.email, phone=row.phone
    )


def delivery_status(row: DeliveryRecord) -> DeliveryStatus:
    """Build the public status while its row is loaded."""
    return DeliveryStatus(
        id=row.id,
        batch_id=row.batch_id,
        provider=row.provider,
        template=row.template_label,
        recipient=delivery_recipient(row),
        status=DeliveryState(row.status),
        attempts=row.attempts,
        message_id=row.message_id,
        reason=row.reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
        next_attempt_at=row.next_attempt_at,
        acknowledged_at=row.acknowledged_at,
        error_code=ErrorCode(row.error_code) if row.error_code else None,
        terminal=row.terminal,
        completed_at=row.completed_at,
    )
