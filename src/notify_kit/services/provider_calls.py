from collections.abc import Awaitable, Callable
from typing import TypeVar

from notify_kit.errors.notifier_error import NotifierError
from notify_kit.errors.provider_error import ProviderError
from notify_kit.models.error_code import ErrorCode

T = TypeVar("T")


async def provider_call(
    name: str, operation: str, call: Callable[[], Awaitable[T]]
) -> T:
    """Translate provider exceptions without leaking unexpected exception contents."""
    try:
        return await call()
    except ProviderError as error:
        raise NotifierError(
            error.code, error.detail, provider=name, operation=operation
        ) from None
    except Exception:
        raise NotifierError(
            ErrorCode.PROVIDER_UNEXPECTED_ERROR,
            "Provider operation failed unexpectedly",
            provider=name,
            operation=operation,
        ) from None
