from pydantic import EmailStr, Field, SecretStr

from app.schemas.api_model import ApiModel


class EmailSettings(ApiModel):
    """Explicit provider credentials and sender identity; never persisted in jobs."""

    api_key: SecretStr = Field(repr=False)
    from_email: EmailStr
    from_name: str | None = None
