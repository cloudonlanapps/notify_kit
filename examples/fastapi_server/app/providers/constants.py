"""Transport configuration and validation bounds for example providers."""

RESEND_URL = "https://api.resend.com/emails"
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
EMAIL_TIMEOUT_SECONDS = 30
MAX_PROVIDER_DETAIL_LENGTH = 500
PHONE_PATTERN = r"\+[1-9][0-9]{7,14}"
