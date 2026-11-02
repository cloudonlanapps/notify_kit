import asyncio
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from notify_kit import (
    CompletionHandler,
    DatabaseStorage,
    ErrorCode,
    Notifier,
    NotifierError,
    NotifyProvider,
    RetentionPolicy,
    RetryPolicy,
    WorkerPolicy,
)
from sqlalchemy.exc import SQLAlchemyError

from app.constants import API_PREFIX, DEFAULT_DATABASE_URL
from app.providers.factory import build_providers
from app.routers import notifications, providers, templates, worker
from app.schemas.error_response import ErrorResponse
from app.schemas.health_response import HealthResponse
from app.services.notifications import NotificationService
from app.services.worker_monitor import report_worker_failure


def create_app(
    *,
    database_url: str = DEFAULT_DATABASE_URL,
    registered_providers: Mapping[str, NotifyProvider] | None = None,
    retry_policy: RetryPolicy | None = None,
    worker_policy: WorkerPolicy | None = None,
    retention_policy: RetentionPolicy | None = None,
    completion_handler: CompletionHandler | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """Configure explicit storage and application-owned providers for the example."""
    configured = (
        dict(registered_providers) if registered_providers is not None else None
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        storage = DatabaseStorage(url=database_url)
        try:
            active_providers = (
                configured if configured is not None else build_providers()
            )
            notifier = Notifier(
                storage=storage,
                providers=active_providers,
                retry_policy=retry_policy,
                worker_policy=worker_policy,
                retention_policy=retention_policy,
                completion_handler=completion_handler,
            )
            await notifier.initialize()
            application.state.notification_service = NotificationService(
                notifier, active_providers
            )
            stop = asyncio.Event()
            task = (
                asyncio.create_task(notifier.run_forever(stop=stop))
                if start_worker
                else None
            )
            if task is not None:
                task.add_done_callback(report_worker_failure)
            try:
                yield
            finally:
                stop.set()
                if task is not None:
                    await task
        finally:
            await storage.aclose()

    application = FastAPI(
        title="notify_kit example server",
        version="0.1.0",
        lifespan=lifespan,
        description="Manual provider, template and persistent delivery exercise API.",
    )

    async def not_found(request: Request, error: KeyError) -> JSONResponse:
        """Translate missing resources without leaking internal keys."""
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorResponse(
                code="not_found", detail="Requested resource was not found"
            ).model_dump(),
        )

    async def invalid_request(request: Request, error: ValueError) -> JSONResponse:
        """Translate rejected package operations into a conflict."""
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=ErrorResponse(
                code="request_conflict", detail=str(error)
            ).model_dump(),
        )

    async def notifier_error(request: Request, error: NotifierError) -> JSONResponse:
        """Expose stable notifier codes and the provider-authored safe detail string."""
        if error.code == ErrorCode.STORAGE_ERROR:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif error.code in (ErrorCode.NOT_FOUND, ErrorCode.PROVIDER_NOT_REGISTERED):
            code = status.HTTP_404_NOT_FOUND
        elif error.code in (
            ErrorCode.RECIPIENT_INVALID,
            ErrorCode.INVALID_REQUEST,
            ErrorCode.TEMPLATE_UNAVAILABLE,
        ):
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
        else:
            code = status.HTTP_409_CONFLICT
        return JSONResponse(
            status_code=code,
            content=ErrorResponse(
                code=error.code.value,
                detail=error.detail,
                provider=error.provider,
                operation=error.operation,
            ).model_dump(),
        )

    async def storage_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        """Hide database parameters and driver details."""
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(
                code="storage_unavailable", detail="Database operation failed"
            ).model_dump(),
        )

    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        """Keep request validation errors consistent with the documented schema."""
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=ErrorResponse(
                code="invalid_request",
                detail="Request does not match the endpoint schema",
            ).model_dump(),
        )

    application.add_exception_handler(RequestValidationError, validation_error)
    application.add_exception_handler(KeyError, not_found)
    application.add_exception_handler(ValueError, invalid_request)
    application.add_exception_handler(NotifierError, notifier_error)
    application.add_exception_handler(SQLAlchemyError, storage_error)
    errors = {
        code: {"model": ErrorResponse}
        for code in (
            status.HTTP_404_NOT_FOUND,
            status.HTTP_409_CONFLICT,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    }
    for router in (
        providers.router,
        templates.router,
        notifications.router,
        worker.router,
    ):
        application.include_router(router, prefix=API_PREFIX, responses=errors)

    @application.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        """Report readiness after the lifespan initialized the database."""
        return HealthResponse(ready=True)

    return application


app = create_app()
