import time
from uuid import uuid4

from sqlalchemy import delete, or_, select

from notify_kit.constants import DEFAULT_WORKER_BATCH_SIZE
from notify_kit.db.database import Database
from notify_kit.db.models.batch_record import BatchRecord
from notify_kit.db.models.completion_record import CompletionRecord
from notify_kit.db.models.delivery_record import DeliveryRecord
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.completion_state import CompletionState
from notify_kit.models.completion_status import CompletionStatus
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.retention_policy import RetentionPolicy


class CompletionStore:
    """Durable completion leases, independent retries, observable exhaustion and cleanup."""

    def __init__(self, database: Database) -> None:
        """Attach kit storage transactions."""
        self._database = database

    @staticmethod
    def _status(row: CompletionRecord) -> CompletionStatus:
        return CompletionStatus(
            row.id,
            row.delivery_id,
            CompletionState(row.status),
            row.attempts,
            row.reason,
            row.next_attempt_at,
        )

    async def get(self, delivery_id: str) -> CompletionStatus:
        """Query completion handling independently from notification delivery."""
        async with self._database.session() as session:
            row = await session.scalar(
                select(CompletionRecord).where(
                    CompletionRecord.delivery_id == delivery_id
                )
            )
            if row is None:
                raise NotifierError(ErrorCode.NOT_FOUND, "Completion event not found")
            return self._status(row)

    async def claim(
        self, *, lease_seconds: float, policy: RetentionPolicy
    ) -> tuple[CompletionStatus, str] | None:
        """Claim one due event or expired handler lease; keep its stable event ID."""
        now = time.time()
        async with self._database.session(write=True) as session:
            statement = (
                select(CompletionRecord)
                .where(
                    or_(
                        (CompletionRecord.status == CompletionState.PENDING)
                        & (CompletionRecord.next_attempt_at <= now),
                        (CompletionRecord.status == CompletionState.PROCESSING)
                        & (CompletionRecord.lease_expires_at <= now),
                    ),
                )
                .order_by(CompletionRecord.created_at)
                .limit(1)
            )
            if not self._database.is_sqlite:
                statement = statement.with_for_update(skip_locked=True)
            row = await session.scalar(statement)
            if row is None:
                return None
            if (
                row.attempts >= policy.callback_max_attempts
                or now >= row.created_at + policy.callback_deadline_seconds
            ):
                row.status, row.reason, row.next_attempt_at = (
                    CompletionState.FAILED,
                    "Completion handling deadline or attempts exhausted",
                    None,
                )
                row.lease_token = None
                row.lease_expires_at = None
                return None
            row.status = CompletionState.PROCESSING
            row.attempts += 1
            token = uuid4().hex
            row.lease_token = token
            row.lease_expires_at = now + lease_seconds
            return self._status(row), token

    async def finish(
        self, delivery_id: str, token: str, *, failed: bool, policy: RetentionPolicy
    ) -> None:
        """Fence expired handlers and never expose callback exception contents."""
        async with self._database.session(write=True) as session:
            row = await session.scalar(
                select(CompletionRecord)
                .where(CompletionRecord.delivery_id == delivery_id)
                .with_for_update()
            )
            if row is None or row.lease_token != token:
                return
            exhausted = (
                row.attempts >= policy.callback_max_attempts
                or time.time() >= row.created_at + policy.callback_deadline_seconds
            )
            row.status = (
                CompletionState.FAILED
                if failed and exhausted
                else CompletionState.PENDING
                if failed
                else CompletionState.HANDLED
            )
            row.reason = "Completion handler failed" if failed else None
            row.next_attempt_at = (
                time.time() + policy.callback_retry_seconds
                if row.status == CompletionState.PENDING
                else None
            )
            row.lease_token = row.lease_expires_at = None

    async def cleanup(
        self, policy: RetentionPolicy, *, max_records: int = DEFAULT_WORKER_BATCH_SIZE
    ) -> None:
        """Expire terminal records only after event handling stops; keep active jobs."""
        now = time.time()
        async with self._database.session(write=True) as session:
            pending = await session.scalars(
                select(CompletionRecord)
                .where(
                    CompletionRecord.status == CompletionState.PENDING,
                    CompletionRecord.created_at + policy.callback_deadline_seconds
                    <= now,
                )
                .limit(max_records)
            )
            for event in pending:
                event.status, event.next_attempt_at, event.reason = (
                    CompletionState.FAILED,
                    None,
                    "Completion handling deadline expired",
                )
            await session.flush()
            rows = await session.scalars(
                select(DeliveryRecord)
                .join(
                    CompletionRecord,
                    CompletionRecord.delivery_id == DeliveryRecord.id,
                )
                .where(
                    DeliveryRecord.terminal.is_(True),
                    CompletionRecord.status.in_(
                        (CompletionState.HANDLED, CompletionState.FAILED)
                    ),
                    or_(
                        DeliveryRecord.content_cleared.is_(False),
                        DeliveryRecord.acknowledged_at
                        <= now - policy.acknowledged_seconds,
                        DeliveryRecord.acknowledged_at.is_(None)
                        & (
                            DeliveryRecord.completed_at
                            <= now - policy.unacknowledged_seconds
                        ),
                    ),
                )
                .order_by(DeliveryRecord.completed_at)
                .limit(max_records)
            )
            for row in rows:
                event = await session.scalar(
                    select(CompletionRecord).where(
                        CompletionRecord.delivery_id == row.id
                    )
                )
                if event is None or event.status not in (
                    CompletionState.HANDLED,
                    CompletionState.FAILED,
                ):
                    continue
                # Once callbacks stop, remove prepared contents even while retaining status.
                row.prepared = {}
                row.content_cleared = True
                base = (
                    row.acknowledged_at
                    if row.acknowledged_at is not None
                    else row.completed_at
                )
                retention = (
                    policy.acknowledged_seconds
                    if row.acknowledged_at is not None
                    else policy.unacknowledged_seconds
                )
                if base is not None and now >= base + retention:
                    await session.delete(event)
                    await session.flush()
                    await session.delete(row)
            await session.flush()
            # Idempotency and facts have the same lifetime as the batch's delivery records.
            await session.execute(
                delete(BatchRecord).where(
                    ~select(DeliveryRecord.id)
                    .where(DeliveryRecord.batch_id == BatchRecord.id)
                    .exists()
                )
            )
