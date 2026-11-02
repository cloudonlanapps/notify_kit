from dataclasses import dataclass

from notify_kit.constants import INITIAL_TEMPLATE_REVISION
from notify_kit.types import Payload


@dataclass(frozen=True)
class Template:
    """Caller-defined notification content and its storage revision."""

    label: str
    definition: Payload
    revision: int = INITIAL_TEMPLATE_REVISION
