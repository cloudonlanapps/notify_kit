from dataclasses import asdict
from string import Template as TextTemplate

from notify_kit import Payload, ProviderError, Recipient


def template_values(facts: Payload, recipient: Recipient) -> dict[str, str]:
    """Combine shared facts with each recipient's non-null identity/contact values."""
    values = {**facts, **{k: v for k, v in asdict(recipient).items() if v is not None}}
    return {key: str(value) for key, value in values.items()}


def validate_pattern(pattern: str) -> TextTemplate:
    """Require valid literal substitution syntax; no expressions or evaluation."""
    template = TextTemplate(pattern)
    if not template.is_valid():
        raise ProviderError("Invalid placeholder syntax; use $name or ${name}")
    return template


def substitute(pattern: str, values: dict[str, str]) -> str:
    """Resolve a pattern once without recursively interpreting inserted values."""
    try:
        return validate_pattern(pattern).substitute(values)
    except KeyError as error:
        raise ProviderError(f"Missing fact: {error.args[0]}") from None
