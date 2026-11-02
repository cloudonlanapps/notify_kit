from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notify_kit.db.models.delivery_record import DeliveryRecord
from notify_kit.db.models.template_record import TemplateRecord
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.error_code import ErrorCode


async def locked_template(session: AsyncSession, label: str) -> TemplateRecord:
    """Lock a parent template consistently before submission or lifecycle changes."""
    row = await session.scalar(
        select(TemplateRecord).where(TemplateRecord.label == label).with_for_update()
    )
    if row is None:
        raise NotifierError(ErrorCode.NOT_FOUND, f"Template not found: {label}")
    return row


def require_idle(row: TemplateRecord, token: str | None = None) -> None:
    """Reject changes/submission while an explicit provider lifecycle operation runs."""
    if row.operation_token is not None and row.operation_token != token:
        raise NotifierError(
            ErrorCode.TEMPLATE_BUSY, "Template has a provider operation in progress"
        )


async def require_no_active_jobs(session: AsyncSession, label: str) -> None:
    """Protect remote references still used by pending or uncertain deliveries."""
    active = await session.scalar(
        select(DeliveryRecord.id)
        .where(
            DeliveryRecord.template_label == label,
            DeliveryRecord.terminal.is_(False),
        )
        .limit(1)
    )
    if active is not None:
        raise NotifierError(
            ErrorCode.TEMPLATE_IN_USE, "Template has unfinished deliveries"
        )
