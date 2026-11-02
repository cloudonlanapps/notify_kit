from email.utils import formataddr

from notify_kit import Payload, Recipient

from app.providers.constants import RESEND_URL
from app.providers.http_email import HttpEmailProvider


class ResendProvider(HttpEmailProvider):
    """Resend inline transactional email, following club_server's mailer payload."""

    def endpoint(self) -> str:
        """Use Resend's email sending endpoint."""
        return RESEND_URL

    def headers(self, idempotency_key: str) -> dict[str, str]:
        """Keep authentication per instance and use each delivery's stable key."""
        return {
            "Authorization": f"Bearer {self._settings.api_key.get_secret_value()}",
            "Idempotency-Key": idempotency_key,
        }

    def payload(
        self, recipient: Recipient, prepared: Payload, idempotency_key: str
    ) -> Payload:
        """Send the snapshotted sender, subject and alternative HTML/plain text."""
        sender = formataddr(
            (str(prepared.get("from_name") or ""), str(prepared["from_email"]))
        )
        return {
            "from": sender,
            "to": [str(recipient.email)],
            "subject": prepared["subject"],
            "html": prepared["html"],
            "text": prepared["text"],
        }

    def message_id(self, response: dict[str, object]) -> str | None:
        """Read Resend's accepted email identifier."""
        value = response.get("id")
        return value if isinstance(value, str) and value else None
