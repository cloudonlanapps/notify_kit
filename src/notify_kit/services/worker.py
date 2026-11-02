import asyncio
import time
from collections.abc import Mapping

from notify_kit.completion_handler import CompletionHandler
from notify_kit.constants import BACKOFF_MULTIPLIER, MAX_BACKOFF_EXPONENT, MIN_ATTEMPTS
from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.claimed_delivery import ClaimedDelivery
from notify_kit.models.completion_event import CompletionEvent
from notify_kit.models.delivery_state import DeliveryState
from notify_kit.models.delivery_status import DeliveryStatus
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.provider_result import ProviderResult
from notify_kit.models.provider_state import ProviderState
from notify_kit.models.retention_policy import RetentionPolicy
from notify_kit.models.retry_policy import RetryPolicy
from notify_kit.models.worker_policy import WorkerPolicy
from notify_kit.provider import NotifyProvider
from notify_kit.services.provider_calls import provider_call
from notify_kit.services.serialization import checked_result
from notify_kit.storage.database_storage import DatabaseStorage


class Worker:
    """Delivery/status attempts and independent durable completion dispatch."""

    def __init__(
        self,
        storage: DatabaseStorage,
        providers: Mapping[str, NotifyProvider],
        *,
        retry: RetryPolicy,
        policy: WorkerPolicy,
        retention: RetentionPolicy,
        handler: CompletionHandler | None,
    ) -> None:
        """Keep policies and caller-owned providers/handler outside persisted jobs."""
        self.storage, self.providers = storage, providers
        self.retry, self.policy, self.retention, self.handler = (
            retry,
            policy,
            retention,
            handler,
        )

    async def run_once(self, max_jobs: int) -> tuple[DeliveryStatus, ...]:
        """Process a bounded batch with a full timeout for each provider operation."""
        await self.storage.deliveries.report_missing_providers(
            self.providers.keys(), max_records=max_jobs
        )
        results: list[DeliveryStatus] = []
        for _ in range(max_jobs):
            job = await self.storage.deliveries.claim(
                self.providers.keys(),
                lease_seconds=self.policy.lease_seconds,
                max_age_seconds=self.policy.max_age_seconds,
            )
            if job is None:
                break
            result = await self._attempt(job)
            state, next_due, terminal = self._transition(job, result)
            saved = await self.storage.deliveries.finish(
                job,
                status=state,
                result=result,
                next_attempt_at=next_due,
                terminal=terminal,
            )
            if saved:
                results.append(saved)
        await self._dispatch(max_jobs)
        await self.storage.completions.cleanup(self.retention, max_records=max_jobs)
        return tuple(results)

    async def _attempt(self, job: ClaimedDelivery) -> ProviderResult:
        if time.time() >= job.created_at + self.policy.max_age_seconds:
            if job.reconcile:
                state = (
                    ProviderState.ACCEPTED
                    if job.previous_status == DeliveryState.ACCEPTED
                    else ProviderState.UNKNOWN
                )
                return ProviderResult(
                    state,
                    message_id=job.message_id,
                    reason="Delivery confirmation deadline reached; no resend attempted",
                    error_code=ErrorCode.DELIVERY_EXPIRED,
                )
            return ProviderResult(
                ProviderState.PERMANENT_FAILURE,
                reason="Delivery age limit reached",
                error_code=ErrorCode.DELIVERY_EXPIRED,
            )
        provider = self.providers[job.provider]
        if job.reconcile and not provider.supports_delivery_status:
            return ProviderResult(
                ProviderState.ACCEPTED
                if job.previous_status == DeliveryState.ACCEPTED
                else ProviderState.UNKNOWN,
                message_id=job.message_id,
                reason="Provider does not support delivery confirmation",
            )
        try:
            async with asyncio.timeout(self.policy.operation_timeout_seconds):
                if job.reconcile:
                    result = await provider_call(
                        job.provider,
                        "check_delivery",
                        lambda: provider.check_delivery(
                            message_id=job.message_id, idempotency_key=job.id
                        ),
                    )
                    return checked_result(result)
                result = await provider_call(
                    job.provider,
                    "send",
                    lambda: provider.send(
                        recipient=job.recipient,
                        prepared=job.prepared,
                        idempotency_key=job.id,
                    ),
                )
                return checked_result(result)
        except NotifierError as error:
            # Provider-authored permanent failures are explicit; unexpected throws
            # after a send may mean acceptance and must not authorize retries.
            if error.code != ErrorCode.PROVIDER_UNEXPECTED_ERROR and not job.reconcile:
                return ProviderResult(
                    ProviderState.PERMANENT_FAILURE,
                    reason=error.detail,
                    error_code=error.code,
                )
            return ProviderResult(
                ProviderState.UNKNOWN,
                reason=error.detail,
                error_code=ErrorCode.DELIVERY_UNKNOWN,
            )
        except TimeoutError:
            return ProviderResult(
                ProviderState.UNKNOWN,
                reason="Provider operation timed out; outcome uncertain",
                error_code=ErrorCode.DELIVERY_UNKNOWN,
            )

    def _transition(
        self, job: ClaimedDelivery, result: ProviderResult
    ) -> tuple[DeliveryState, float | None, bool]:
        now = time.time()
        expired = now >= job.created_at + self.policy.max_age_seconds
        if result.status == ProviderState.DELIVERED:
            return DeliveryState.DELIVERED, None, True
        if result.status == ProviderState.PERMANENT_FAILURE:
            return DeliveryState.FAILED, None, True
        if result.status == ProviderState.TEMPORARY_FAILURE:
            if expired or job.attempts >= self.retry.max_attempts:
                return DeliveryState.FAILED, None, True
            delay = min(
                self.retry.max_delay_seconds,
                self.retry.initial_delay_seconds
                * BACKOFF_MULTIPLIER
                ** min(job.attempts - MIN_ATTEMPTS, MAX_BACKOFF_EXPONENT),
            )
            due = now + max(delay, result.retry_after_seconds or 0)
            # A reconciliation's temporary failure explicitly means not delivered
            # and safe to retry, per the provider contract.
            return (
                DeliveryState.RETRY_SCHEDULED,
                min(due, job.created_at + self.policy.max_age_seconds),
                False,
            )
        state = (
            DeliveryState.ACCEPTED
            if result.status == ProviderState.ACCEPTED
            or (job.reconcile and job.previous_status == DeliveryState.ACCEPTED)
            else DeliveryState.UNKNOWN
        )
        if expired:
            return state, None, True
        provider = self.providers[job.provider]
        if not provider.supports_delivery_status:
            if state == DeliveryState.ACCEPTED:
                return state, None, True
            return state, job.created_at + self.policy.max_age_seconds, False
        return (
            state,
            min(
                now + self.policy.status_poll_seconds,
                job.created_at + self.policy.max_age_seconds,
            ),
            False,
        )

    async def _dispatch(self, max_jobs: int) -> None:
        for _ in range(max_jobs):
            claimed = await self.storage.completions.claim(
                lease_seconds=self.policy.lease_seconds, policy=self.retention
            )
            if claimed is None:
                break
            event, token = claimed
            if token is None:
                continue
            failed = False
            if self.handler is not None:
                try:
                    async with asyncio.timeout(self.policy.operation_timeout_seconds):
                        await self.handler(
                            CompletionEvent(
                                event.id,
                                await self.storage.deliveries.get(event.delivery_id),
                            )
                        )
                except Exception:
                    failed = True
            await self.storage.completions.finish(
                event.delivery_id, token, failed=failed, policy=self.retention
            )
