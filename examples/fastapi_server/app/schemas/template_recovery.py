from typing import Literal

from notify_kit import TemplateOperation

from app.schemas.api_model import ApiModel


class TemplateRecovery(ApiModel):
    """Operator confirmation that the original operation has stopped before recovery."""

    operation: TemplateOperation
    confirmed_stopped: Literal[True]
