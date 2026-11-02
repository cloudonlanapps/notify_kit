import hashlib
import time
from collections.abc import Collection, Sequence
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from notify_kit.constants import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_MAX_AGE_SECONDS,
    DEFAULT_WORKER_BATCH_SIZE,
)
from notify_kit.db.database import Database
from notify_kit.db.models.batch_record import BatchRecord
from notify_kit.db.models.completion_record import CompletionRecord
from notify_kit.db.models.delivery_record import DeliveryRecord
from notify_kit.db.models.template_provider_record import TemplateProviderRecord
from notify_kit.db.template_guards import locked_template, require_idle
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.claimed_delivery import ClaimedDelivery
from notify_kit.models.completion_state import CompletionState
from notify_kit.models.delivery_reference import DeliveryReference
from notify_kit.models.delivery_state import DeliveryState
from notify_kit.models.delivery_status import DeliveryStatus
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.prepared_delivery import PreparedDelivery
from notify_kit.models.provider_result import ProviderResult
from notify_kit.models.recipient import Recipient
from notify_kit.models.send_receipt import SendReceipt
from notify_kit.storage.job_store import JobStore
from notify_kit.types import Payload


class DeliveryStore:
    """Own delivery transactions and database-aware atomic worker claims."""

    def __init__(self, database: Database) -> None:
        """Attach the instance-owned database session factory."""
        self._database = database
        self._jobs = JobStore(database)

    @staticmethod
    async def _receipt(session: AsyncSession, batch_id: str) -> SendReceipt:
        rows = await session.scalars(
            select(DeliveryRecord)
            .where(DeliveryRecord.batch_id == batch_id)
            .order_by(DeliveryRecord.position)
        )
        return SendReceipt(
            batch_id,
            tuple(
                DeliveryReference(
                    row.id,
                    Recipient(
                        username=row.username,
                        name=row.display_name,
                        email=row.email,
                        phone=row.phone,
                    ),
                )
                for row in rows
            ),
        )

    async def _existing(
        self,
        session: AsyncSession,
        key: str,
        request: str,
    ) -> SendReceipt | None:
        row = await session.scalar(
            select(BatchRecord).where(BatchRecord.idempotency_key == key)
        )
        if row is None:
            return None
        if row.request not in (request, hashlib.sha256(request.encode()).hexdigest()):
            raise NotifierError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Idempotency key was already used for different inputs",
            )
        count = await session.scalar(
            select(func.count())
            .select_from(DeliveryRecord)
            .where(DeliveryRecord.batch_id == row.id)
        )
        if count != row.recipient_count:
            raise NotifierError(
                ErrorCode.IDEMPOTENCY_EXPIRED,
                "Some recipient records expired; this retained request key cannot be reused for submission",
            )
        return await self._receipt(session, row.id)

    async def find_request(self, key: str, request: str) -> SendReceipt | None:
        """Return a prior submission or reject reuse with different inputs."""
        async with self._database.session() as session:
            return await self._existing(session, key, request)

    async def enqueue(
        self,
        *,
        provider: str,
        template: str,
        request: str,
        idempotency_key: str,
        deliveries: Sequence[PreparedDelivery],
        template_revision: int,
        expected_metadata: Payload | None,
    ) -> SendReceipt:
        """Commit the batch atomically and reconcile concurrent idempotency keys."""
        try:
            async with self._database.session(write=True) as session:
                previous = await self._existing(session, idempotency_key, request)
                if previous is not None:
                    return previous
                parent = await locked_template(session, template)
                require_idle(parent)
                if parent.revision != template_revision:
                    raise NotifierError(
                        ErrorCode.TEMPLATE_CHANGED,
                        "Template changed during preparation; retry",
                    )
                link = await session.get(TemplateProviderRecord, (template, provider))
                current_metadata = None if link is None else link.provider_metadata
                if current_metadata != expected_metadata:
                    raise NotifierError(
                        ErrorCode.TEMPLATE_CHANGED,
                        "Provider linkage changed during preparation; retry",
                    )
                batch_id = uuid4().hex
                session.add(
                    BatchRecord(
                        recipient_count=len(deliveries),
                        id=batch_id,
                        idempotency_key=idempotency_key,
                        request=hashlib.sha256(request.encode()).hexdigest(),
                    )
                )
                # Flush the parent before children without relying on relationships.
                await session.flush()
                now = time.time()
                for position, delivery in enumerate(deliveries):
                    session.add(
                        DeliveryRecord(
                            id=delivery.id,
                            batch_id=batch_id,
                            position=position,
                            provider=provider,
                            template_label=template,
                            username=delivery.recipient.username,
                            email=delivery.recipient.email,
                            phone=delivery.recipient.phone,
                            display_name=delivery.recipient.name,
                            prepared=delivery.payload,
                            status=delivery.status.value,
                            terminal=delivery.status == DeliveryState.FAILED,
                            completed_at=now
                            if delivery.status == DeliveryState.FAILED
                            else None,
                            attempts=0,
                            reason=delivery.reason,
                            error_code=delivery.error_code,
                            created_at=now,
                            updated_at=now,
                            next_attempt_at=now
                            if delivery.status == DeliveryState.QUEUED
                            else None,
                        )
                    )
                await session.flush()
                for delivery in deliveries:
                    if delivery.status == DeliveryState.FAILED:
                        session.add(
                            CompletionRecord(
                                id=delivery.id,
                                delivery_id=delivery.id,
                                status=CompletionState.PENDING,
                                attempts=0,
                                created_at=now,
                                next_attempt_at=now,
                            )
                        )
                await session.flush()
                receipt = await self._receipt(session, batch_id)
            return receipt
        except IntegrityError:
            # The unique key can race on PostgreSQL. A fresh transaction sees the
            # winning committed request; unrelated constraint failures propagate.
            previous = await self.find_request(idempotency_key, request)
            if previous is None:
                raise NotifierError(
                    ErrorCode.STORAGE_ERROR, "Unable to persist delivery batch"
                ) from None
            return previous

    @staticmethod
    def _status(row: DeliveryRecord) -> DeliveryStatus:
        return DeliveryStatus(
            id=row.id,
            batch_id=row.batch_id,
            provider=row.provider,
            template=row.template_label,
            recipient=Recipient(
                username=row.username,
                name=row.display_name,
                email=row.email,
                phone=row.phone,
            ),
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

    async def get(self, delivery_id: str) -> DeliveryStatus:
        """Retrieve an individual status or raise a not-found NotifierError."""
        async with self._database.session() as session:
            row = await session.get(DeliveryRecord, delivery_id)
            if row is None:
                raise NotifierError(
                    ErrorCode.NOT_FOUND, f"Delivery not found: {delivery_id}"
                )
            return self._status(row)

    async def get_batch(self, batch_id: str) -> tuple[DeliveryStatus, ...]:
        """Retrieve a batch in submission order or raise a not-found NotifierError."""
        async with self._database.session() as session:
            if await session.get(BatchRecord, batch_id) is None:
                raise NotifierError(ErrorCode.NOT_FOUND, f"Batch not found: {batch_id}")
            rows = await session.scalars(
                select(DeliveryRecord)
                .where(DeliveryRecord.batch_id == batch_id)
                .order_by(DeliveryRecord.position)
            )
            return tuple(self._status(row) for row in rows)

    async def claim(
        self,
        providers: Collection[str],
        *,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    ) -> ClaimedDelivery | None:
        """Claim due work through the fenced job store."""
        return await self._jobs.claim(
            providers, lease_seconds=lease_seconds, max_age_seconds=max_age_seconds
        )

    async def finish(
        self,
        job: ClaimedDelivery,
        *,
        status: DeliveryState,
        result: ProviderResult,
        next_attempt_at: float | None,
        terminal: bool,
    ) -> bool:
        """Commit one fenced attempt and its optional terminal completion event."""
        return await self._jobs.finish(
            job,
            status=status,
            result=result,
            next_attempt_at=next_attempt_at,
            terminal=terminal,
        )

    async def acknowledge(self, delivery_id: str) -> None:
        """Record application acknowledgement only after a terminal outcome."""
        async with self._database.session(write=True) as session:
            row = await session.scalar(
                select(DeliveryRecord)
                .where(DeliveryRecord.id == delivery_id)
                .with_for_update()
            )
            if row is None:
                raise NotifierError(ErrorCode.NOT_FOUND, "Delivery not found")
            if not row.terminal:
                raise NotifierError(
                    ErrorCode.INVALID_STATE,
                    "Only terminal deliveries can be acknowledged",
                )
            if row.acknowledged_at is None:
                row.acknowledged_at = time.time()

    async def report_missing_providers(
        self,
        providers: Collection[str],
        *,
        max_records: int = DEFAULT_WORKER_BATCH_SIZE,
    ) -> None:
        """Expose missing provider registrations without discarding their work."""
        await self._jobs.report_missing_providers(providers, max_records=max_records)
