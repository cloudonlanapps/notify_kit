from fastapi import APIRouter

from app.dependencies import ServiceDependency
from app.schemas.delivery_response import DeliveryResponse
from app.schemas.worker_request import WorkerRequest

router = APIRouter(prefix="/worker", tags=["worker"])


@router.post("/run-once", response_model=list[DeliveryResponse])
async def run_once(
    request: WorkerRequest, service: ServiceDependency
) -> list[DeliveryResponse]:
    """Process a bounded number of due attempts, returning updated statuses."""
    return await service.run_once(request.max_jobs)
