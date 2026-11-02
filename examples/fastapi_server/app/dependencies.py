from typing import Annotated

from fastapi import Depends, Request

from app.services.notifications import NotificationService


def notification_service(request: Request) -> NotificationService:
    """Resolve the lifespan-owned service without constructing per-request engines."""
    return request.app.state.notification_service


type ServiceDependency = Annotated[NotificationService, Depends(notification_service)]
