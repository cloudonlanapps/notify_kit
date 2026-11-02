from notify_kit.models.error_code import ErrorCode


class NotifierError(Exception):
    """Standard kit error with safe provider detail and operation context."""

    def __init__(
        self,
        code: ErrorCode,
        detail: str,
        *,
        provider: str | None = None,
        operation: str | None = None,
    ) -> None:
        """Preserve stable classification separately from diagnostic text."""
        self.code = code
        self.detail = detail
        self.provider = provider
        self.operation = operation
        super().__init__(detail)
