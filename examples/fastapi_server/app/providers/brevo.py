from notify_kit import Payload, Recipient

from app.providers.constants import BREVO_URL
from app.providers.http_email import HttpEmailProvider


class BrevoProvider(HttpEmailProvider):
    """Brevo transactional email using club_server's sender/to/content structure."""

    def endpoint(self) -> str:
        """Use Brevo's transactional email endpoint."""
        return BREVO_URL

    def headers(self, idempotency_key: str) -> dict[str, str]:
        """Authenticate using the configured provider instance's key."""
        return {
            "api-key": self._settings.api_key.get_secret_value(),
            "accept": "application/json",
        }

    def payload(
        self, recipient: Recipient, prepared: Payload, idempotency_key: str
    ) -> Payload:
        """Send inline HTML with a personalized recipient and vendor idempotency key."""
        sender: Payload = {"email": prepared["from_email"]}
        if prepared.get("from_name"):
            sender["name"] = prepared["from_name"]
        destination: Payload = {"email": recipient.email}
        if recipient.name:
            destination["name"] = recipient.name
        # Current Brevo documentation specifies one body type per request.
        return {
            "sender": sender,
            "to": [destination],
            "subject": prepared["subject"],
            "htmlContent": prepared["html"],
            "headers": {"idempotencyKey": idempotency_key},
        }

    def message_id(self, response: dict[str, object]) -> str | None:
        """Read Brevo's accepted message identifier."""
        value = response.get("messageId")
        return value if isinstance(value, str) and value else None
