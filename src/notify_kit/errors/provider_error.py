from notify_kit.models.error_code import ErrorCode


class ProviderError(Exception):
    """Provider-authored safe detail; do not include secrets or raw responses."""

    def __init__(
        self, detail: str, *, code: ErrorCode = ErrorCode.PROVIDER_ERROR
    ) -> None:
        """Supply a diagnostic string and optionally a standard error category."""
        self.detail = detail
        self.code = code
        super().__init__(detail)
