from fastapi import APIRouter

from app.dependencies import ServiceDependency
from app.schemas.provider_response import ProviderResponse

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("", response_model=list[ProviderResponse])
async def providers(service: ServiceDependency) -> list[ProviderResponse]:
    """List startup-registered provider instances and local configuration status."""
    return service.providers()


@router.get("/{name}", response_model=ProviderResponse)
async def provider(name: str, service: ServiceDependency) -> ProviderResponse:
    """Check local configuration without a remote health check."""
    return service.provider(name)
