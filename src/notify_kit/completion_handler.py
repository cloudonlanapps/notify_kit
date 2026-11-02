from typing import Protocol

from notify_kit.models.completion_event import CompletionEvent


class CompletionHandler(Protocol):
    """Application callback; handlers must tolerate repeated stable event IDs."""

    async def __call__(self, event: CompletionEvent) -> None:
        """Save application state or raise to retry callback delivery independently."""
        ...
