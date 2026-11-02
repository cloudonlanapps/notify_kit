from dataclasses import dataclass

from notify_kit.models.error_code import ErrorCode
from notify_kit.types import Payload


@dataclass(frozen=True)
class TemplateCheck:
    """Template usability and refreshed provider-owned metadata."""

    available: bool
    metadata: Payload
    reason: str | None = None
    error_code: ErrorCode | None = None
