from fastapi import APIRouter, Response, status

from app.dependencies import ServiceDependency
from app.schemas.link_response import LinkResponse
from app.schemas.template_create import TemplateCreate
from app.schemas.template_recovery import TemplateRecovery
from app.schemas.template_response import TemplateResponse
from app.schemas.template_update import TemplateUpdate

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create(
    request: TemplateCreate, service: ServiceDependency
) -> TemplateResponse:
    """Create a uniquely labelled definition."""
    return await service.create(request)


@router.get("", response_model=list[TemplateResponse])
async def list_templates(service: ServiceDependency) -> list[TemplateResponse]:
    """List stored templates."""
    return await service.templates()


@router.get("/{label}", response_model=TemplateResponse)
async def get(label: str, service: ServiceDependency) -> TemplateResponse:
    """Retrieve one definition."""
    return await service.template(label)


@router.put("/{label}", response_model=TemplateResponse)
async def update(
    label: str, request: TemplateUpdate, service: ServiceDependency
) -> TemplateResponse:
    """Replace the complete definition and increment its revision."""
    return await service.update(label, request)


@router.delete("/{label}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(label: str, service: ServiceDependency) -> Response:
    """Delete a definition and linkage, retaining queued deliveries."""
    await service.delete(label)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{label}/providers/{provider}/register", response_model=LinkResponse)
async def register(
    label: str, provider: str, service: ServiceDependency
) -> LinkResponse:
    """Explicitly register with a provider and store its metadata."""
    return await service.register(provider, label)


@router.get("/{label}/providers/{provider}", response_model=LinkResponse)
async def registration(
    label: str, provider: str, service: ServiceDependency
) -> LinkResponse:
    """Read cached metadata; null means there is no linkage row."""
    return await service.registration(provider, label)


@router.post("/{label}/providers/{provider}/refresh", response_model=LinkResponse)
async def refresh(
    label: str, provider: str, service: ServiceDependency
) -> LinkResponse:
    """Check availability and persist refreshed metadata; unavailable returns an error."""
    return await service.registration(provider, label, refresh=True)


@router.put("/{label}/providers/{provider}", response_model=LinkResponse)
async def update_registration(
    label: str, provider: str, service: ServiceDependency
) -> LinkResponse:
    """Update/version the provider registration after editing the local definition."""
    return await service.update_registration(provider, label)


@router.delete("/{label}/providers/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister(label: str, provider: str, service: ServiceDependency) -> Response:
    """Confirm provider removal and remove its linkage; preserve the local definition."""
    await service.unregister(provider, label)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{label}/providers/{provider}/recover", response_model=LinkResponse)
async def recover(
    label: str, provider: str, request: TemplateRecovery, service: ServiceDependency
) -> LinkResponse:
    """Operator recovery only after the old call/process is confirmed stopped."""
    return await service.recover_template(provider, label, request)
