import asyncio
import logging

logger = logging.getLogger(__name__)


def report_worker_failure(task: asyncio.Task[None]) -> None:
    """Report a stopped worker immediately; the application owns restart policy."""
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "Notification worker failed",
            exc_info=(type(error), error, error.__traceback__),
        )
