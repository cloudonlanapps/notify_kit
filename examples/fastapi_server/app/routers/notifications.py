from fastapi import APIRouter, Response, status

from app.dependencies import ServiceDependency
from app.schemas.completion_response import CompletionResponse
from app.schemas.delivery_response import DeliveryResponse
from app.schemas.preview_request import PreviewRequest
from app.schemas.preview_response import PreviewResponse
from app.schemas.send_request import SendRequest
from app.schemas.send_response import SendResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("", response_model=SendResponse, status_code=status.HTTP_202_ACCEPTED)
async def send(request: SendRequest, service: ServiceDependency) -> SendResponse:
    """Queue a batch; this response does not mean delivery has occurred."""
    return await service.send(request)


@router.get("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def delivery(delivery_id: str, service: ServiceDependency) -> DeliveryResponse:
    """Query the status of one recipient's job."""
    return await service.delivery(delivery_id)


@router.get("/batches/{batch_id}", response_model=list[DeliveryResponse])
async def batch(batch_id: str, service: ServiceDependency) -> list[DeliveryResponse]:
    """Query all recipient statuses for a batch."""
    return await service.batch(batch_id)


@router.post("/preview", response_model=PreviewResponse)
async def preview(
    request: PreviewRequest, service: ServiceDependency
) -> PreviewResponse:
    """Inspect prepared content without delivering it."""
    return await service.preview(request)


@router.post(
    "/deliveries/{delivery_id}/acknowledge", status_code=status.HTTP_204_NO_CONTENT
)
async def acknowledge(delivery_id: str, service: ServiceDependency) -> Response:
    """Acknowledge a terminal result after saving application state."""
    await service.acknowledge(delivery_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/deliveries/{delivery_id}/completion", response_model=CompletionResponse)
async def completion(
    delivery_id: str, service: ServiceDependency
) -> CompletionResponse:
    """Inspect completion handling failures independently of delivery."""
    return await service.completion(delivery_id)
