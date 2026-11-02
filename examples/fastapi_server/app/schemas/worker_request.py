from pydantic import Field

from app.constants import DEFAULT_WORKER_JOBS, MAX_WORKER_JOBS, MIN_WORKER_JOBS
from app.schemas.api_model import ApiModel


class WorkerRequest(ApiModel):
    """Bound the number of delivery attempts in one invocation."""

    max_jobs: int = Field(
        default=DEFAULT_WORKER_JOBS, ge=MIN_WORKER_JOBS, le=MAX_WORKER_JOBS
    )
