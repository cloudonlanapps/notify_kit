import time
from collections.abc import Collection
from uuid import uuid4

from sqlalchemy import or_, select, update

from notify_kit.constants import DEFAULT_MAX_AGE_SECONDS, DEFAULT_WORKER_BATCH_SIZE
from notify_kit.db.database import Database
from notify_kit.db.delivery_mapping import delivery_recipient, delivery_status
from notify_kit.db.models.completion_record import CompletionRecord
from notify_kit.db.models.delivery_record import DeliveryRecord
from notify_kit.models.claimed_delivery import ClaimedDelivery
from notify_kit.models.completion_state import CompletionState
from notify_kit.models.delivery_state import DeliveryState
from notify_kit.models.delivery_status import DeliveryStatus
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.provider_result import ProviderResult
from notify_kit.models.provider_state import ProviderState


class JobStore:
    """Atomic fenced claims and terminal/outbox transitions shared across workers."""

    def __init__(self, database: Database) -> None:
        """Attach the shared transaction/session factory."""
        self._database = database

    async def claim(
        self,
        providers: Collection[str],
        *,
        lease_seconds: float,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    ) -> ClaimedDelivery | None:
        """Recover expired claims only for reconciliation, never blind resend."""
        now = time.time()
        statement = (
            select(DeliveryRecord)
            .where(
                DeliveryRecord.terminal.is_(False),
                or_(
                    DeliveryRecord.provider.in_(providers),
                    DeliveryRecord.created_at <= now - max_age_seconds,
                ),
                or_(
                    DeliveryRecord.next_attempt_at <= now,
                    (DeliveryRecord.status == DeliveryState.PROCESSING)
                    & (DeliveryRecord.lease_expires_at <= now),
                ),
            )
            .order_by(DeliveryRecord.created_at, DeliveryRecord.id)
            .limit(1)
        )
        if not self._database.is_sqlite:
            statement = statement.with_for_update(skip_locked=True)
        async with self._database.session(write=True) as session:
            row = await session.scalar(statement)
            if row is None:
                return None
            previous = row.status
            reconcile = previous in (
                DeliveryState.ACCEPTED,
                DeliveryState.UNKNOWN,
                DeliveryState.PROCESSING,
            )
            if not reconcile:
                row.attempts += 1
            row.status = DeliveryState.PROCESSING.value
            token = uuid4().hex
            row.lease_token = token
            row.lease_expires_at = now + lease_seconds
            row.next_attempt_at = None
            row.updated_at = now
            return ClaimedDelivery(
                id=row.id,
                provider=row.provider,
                recipient=delivery_recipient(row),
                prepared=row.prepared,
                attempts=row.attempts,
                lease_token=token,
                created_at=row.created_at,
                message_id=row.message_id,
                reconcile=reconcile,
                previous_status=previous,
            )

    async def finish(
        self,
        job: ClaimedDelivery,
        *,
        status: DeliveryState,
        result: ProviderResult,
        next_attempt_at: float | None,
        terminal: bool,
    ) -> DeliveryStatus | None:
        """Fence stale workers; terminal status and its completion event commit together."""
        async with self._database.session(write=True) as session:
            row = await session.scalar(
                select(DeliveryRecord)
                .where(DeliveryRecord.id == job.id)
                .with_for_update()
            )
            if row is None or row.lease_token != job.lease_token:
                return None
            row.status = status.value
            row.message_id = result.message_id or row.message_id
            row.reason = result.reason
            row.error_code = result.error_code or (
                ErrorCode.PROVIDER_ERROR
                if result.status
                in (ProviderState.TEMPORARY_FAILURE, ProviderState.PERMANENT_FAILURE)
                else ErrorCode.DELIVERY_UNKNOWN
                if result.status == ProviderState.UNKNOWN
                else None
            )
            row.updated_at = time.time()
            row.next_attempt_at = next_attempt_at
            row.terminal = terminal
            row.lease_token = None
            row.lease_expires_at = None
            if terminal:
                row.completed_at = row.updated_at
                session.add(
                    CompletionRecord(
                        id=row.id,
                        delivery_id=row.id,
                        status=CompletionState.PENDING,
                        attempts=0,
                        created_at=row.updated_at,
                        next_attempt_at=row.updated_at,
                    )
                )
            return delivery_status(row)

    async def report_missing_providers(
        self,
        providers: Collection[str],
        *,
        max_records: int = DEFAULT_WORKER_BATCH_SIZE,
    ) -> None:
        """Bound reporting work and avoid overwriting concurrent terminal outcomes."""
        conditions = (
            DeliveryRecord.terminal.is_(False),
            DeliveryRecord.provider.not_in(providers),
            or_(
                DeliveryRecord.error_code.is_(None),
                DeliveryRecord.error_code != ErrorCode.PROVIDER_NOT_REGISTERED,
            ),
        )
        async with self._database.session() as session:
            if (
                await session.scalar(
                    select(DeliveryRecord.id).where(*conditions).limit(1)
                )
                is None
            ):
                return
        async with self._database.session(write=True) as session:
            ids = select(DeliveryRecord.id).where(*conditions).limit(max_records)
            await session.execute(
                update(DeliveryRecord)
                .where(*conditions, DeliveryRecord.id.in_(ids))
                .values(
                    reason="Provider registration is missing at worker startup",
                    error_code=ErrorCode.PROVIDER_NOT_REGISTERED,
                )
            )
