from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable kit error categories; provider diagnostics remain separate strings."""

    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    PROVIDER_NOT_REGISTERED = "provider_not_registered"
    PROVIDER_ERROR = "provider_error"
    PROVIDER_UNEXPECTED_ERROR = "provider_unexpected_error"
    RECIPIENT_INVALID = "recipient_invalid"
    TEMPLATE_UNAVAILABLE = "template_unavailable"
    TEMPLATE_NOT_REGISTERED = "template_not_registered"
    TEMPLATE_CHANGED = "template_changed"
    TEMPLATE_IN_USE = "template_in_use"
    TEMPLATE_HAS_LINKS = "template_has_links"
    TEMPLATE_BUSY = "template_busy"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    DELIVERY_UNKNOWN = "delivery_unknown"
    PROVIDER_ACTION_REQUIRED = "provider_action_required"
    TEMPLATE_PENDING = "template_pending"
    STORAGE_ERROR = "storage_error"
    SCHEMA_MISMATCH = "schema_mismatch"
    DELIVERY_EXPIRED = "delivery_expired"
    INVALID_STATE = "invalid_state"
    IDEMPOTENCY_EXPIRED = "idempotency_expired"
