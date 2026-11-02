from dataclasses import dataclass

from notify_kit.models.completion_state import CompletionState


@dataclass(frozen=True)
class CompletionStatus:
    """Observable callback state, including exhausted retries requiring caller action."""

    id: str
    delivery_id: str
    status: CompletionState
    attempts: int
    reason: str | None
    next_attempt_at: float | None
