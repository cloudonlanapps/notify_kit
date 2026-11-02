import os

from notify_kit import NotifyProvider, ProviderError
from pydantic import ValidationError

from app.constants import DEFAULT_PROVIDER_NAME
from app.providers.brevo import BrevoProvider
from app.providers.console import ConsoleProvider
from app.providers.fake_sms import FakeSmsProvider
from app.providers.resend import ResendProvider
from app.schemas.email_settings import EmailSettings


def build_providers() -> dict[str, NotifyProvider]:
    """Load example-owned startup settings; absent keys leave email adapters disabled.

    The core kit and provider implementations never read the environment. A supplied
    key requires a valid sender; partial configuration fails explicitly.
    """
    providers: dict[str, NotifyProvider] = {
        DEFAULT_PROVIDER_NAME: ConsoleProvider(),
        "fake_sms": FakeSmsProvider(),
    }
    for name, provider_type in (("resend", ResendProvider), ("brevo", BrevoProvider)):
        prefix = name.upper()
        key = os.environ.get(f"{prefix}_API_KEY")
        if key is None:
            continue
        try:
            settings = EmailSettings(
                api_key=key,
                from_email=os.environ.get(f"{prefix}_FROM_EMAIL", ""),
                from_name=os.environ.get(f"{prefix}_FROM_NAME") or None,
            )
        except ValidationError:
            raise ProviderError(
                f"{prefix} requires a valid {prefix}_FROM_EMAIL and API key"
            ) from None
        providers[name] = provider_type(settings)
    return providers
