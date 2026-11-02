from dataclasses import dataclass


@dataclass(frozen=True)
class Recipient:
    """Application identity and optional contacts; providers validate required fields."""

    username: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
