from enum import StrEnum


class TemplateOperation(StrEnum):
    """Explicit mutations supported by the provider template lifecycle."""

    REGISTER = "register"
    UPDATE = "update"
    UNREGISTER = "unregister"
