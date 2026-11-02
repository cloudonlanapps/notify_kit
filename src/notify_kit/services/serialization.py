import json
from typing import cast

from notify_kit.errors.notifier_error import NotifierError
from notify_kit.models.error_code import ErrorCode
from notify_kit.models.provider_result import ProviderResult
from notify_kit.models.provider_state import ProviderState
from notify_kit.models.template_check import TemplateCheck
from notify_kit.types import Payload


def snapshot_payload(value: object) -> Payload:
    """Validate a plugin boundary and detach mutable JSON data before persistence."""
    if not isinstance(value, dict):
        raise NotifierError(
            ErrorCode.PROVIDER_ERROR, "Provider must return a metadata/payload object"
        )
    try:
        return cast(Payload, json.loads(json.dumps(value, allow_nan=False)))
    except (TypeError, ValueError):
        raise NotifierError(
            ErrorCode.PROVIDER_ERROR, "Provider payload must be JSON serializable"
        ) from None


def checked_result(value: object) -> "ProviderResult":
    """Validate plugin results before they can disrupt another recipient's work."""
    if not isinstance(value, ProviderResult) or not _valid_result_fields(
        value.status, value.message_id, value.reason, value.error_code
    ):
        raise NotifierError(
            ErrorCode.PROVIDER_UNEXPECTED_ERROR,
            "Provider returned an invalid delivery result",
        )
    return value


def checked_template(value: object) -> "TemplateCheck":
    """Validate template checks and detach their opaque metadata at plugin boundaries."""
    if not isinstance(value, TemplateCheck) or not _valid_check_fields(
        value.available, value.reason, value.error_code
    ):
        raise NotifierError(
            ErrorCode.PROVIDER_ERROR, "Provider returned an invalid template check"
        )
    return TemplateCheck(
        value.available,
        snapshot_payload(value.metadata),
        value.reason,
        value.error_code,
    )


def _valid_result_fields(
    status: object, message_id: object, reason: object, code: object
) -> bool:
    return (
        isinstance(status, ProviderState)
        and (message_id is None or isinstance(message_id, str))
        and (reason is None or isinstance(reason, str))
        and (code is None or isinstance(code, ErrorCode))
    )


def _valid_check_fields(available: object, reason: object, code: object) -> bool:
    return (
        isinstance(available, bool)
        and (reason is None or isinstance(reason, str))
        and (code is None or isinstance(code, ErrorCode))
    )
