# Example providers

Run the commands below from examples/fastapi_server/ in the repository.

All implementations are application-owned under app/providers/. The kit package is
unchanged. Startup registers console and fake_sms without credentials. Brevo and
Resend are added only when their API keys are configured. GET /v1/providers shows
which instances are registered; GET /v1/providers/{name} validates configuration
locally, without proving that credentials work remotely.

## Fake SMS

Provider name: fake_sms. No credentials, SDK, DLT account or external SMS delivery.
A phone number in international form is required. Internal registrations are stored
as metadata in the kit's SQLite/PostgreSQL linkage table, so they survive restart.
This is not an Indian SMS/DLT adapter.

Create and explicitly register a template:

```bash
curl -sS http://127.0.0.1:8000/v1/templates \
  -H 'Content-Type: application/json' \
  -d '{"label":"sms_receipt","definition":{"body":"Hello $name, received $amount"}}'

curl -sS -X POST \
  http://127.0.0.1:8000/v1/templates/sms_receipt/providers/fake_sms/register
```

Then submit and process:

```bash
curl -sS http://127.0.0.1:8000/v1/notifications \
  -H 'Content-Type: application/json' \
  -d '{"provider":"fake_sms","template":"sms_receipt","recipients":[{"username":"alice","name":"Alice","phone":"+919876543210"},{"username":"bob","name":"Bob"}],"facts":{"amount":500},"idempotency_key":"sms-payment-123"}'

curl -sS http://127.0.0.1:8000/v1/worker/run-once \
  -H 'Content-Type: application/json' -d '{"max_jobs":100}'
```

Alice's job prints this line to the server console and becomes delivered:

```text
SMS:sendto:+919876543210:"Hello Alice, received 500"
```

Bob's missing phone produces an individual failed job with recipient_invalid and
"phone is required for this provider". Query the returned delivery/batch IDs for
the reason. Unregistered SMS templates similarly fail individual preparation with
template_not_registered. Neither case sends anything for the affected recipient.

Check metadata with GET /v1/templates/sms_receipt/providers/fake_sms, refresh with
POST on the /refresh suffix, update with PUT on that provider linkage after editing
the definition, and unregister with DELETE on the linkage. No in-memory registry
or separate provider database is needed. The fake registration includes an ID,
revision, body and content fingerprint. A changed definition must be synchronized
before new sends. Removal confirms deletion of that internal registration.

## Brevo and Resend

These adapters send inline email: they prepare the subject and body first, then
submit them to the vendor's send endpoint.
They use httpx.AsyncClient instead of the synchronous SDKs. Authentication belongs
to each provider instance; no process-global SDK API key is modified. Each attempt
closes its HTTP client, and credentials never enter prepared payloads or jobs.

### Configure at startup

Supply settings in the shell running Uvicorn, then restart the server:

```bash
export RESEND_API_KEY='your-key'
export RESEND_FROM_EMAIL='notifications@your-verified-domain.example'
export RESEND_FROM_NAME='Your application'

export BREVO_API_KEY='your-key'
export BREVO_FROM_EMAIL='notifications@your-verified-domain.example'
export BREVO_FROM_NAME='Your application'

uv run uvicorn app.main:app --reload
```

Configure either provider independently. Keys absent means that provider is not
registered; a key with invalid/missing sender settings fails explicitly. Display
names are optional. The sending domain/sender must be accepted by the service.
The factory reads environment variables in the example application only; providers
and notify_kit receive explicit configuration. Credentials are not accepted through
HTTP endpoints and no .env file is loaded automatically.

Alternatively construct instances directly and pass them to create_app:

```python
from app.main import create_app
from app.providers.brevo import BrevoProvider
from app.providers.resend import ResendProvider
from app.schemas.email_settings import EmailSettings

# Values below come from your own startup secret/configuration source.
app = create_app(
    registered_providers={
        "brevo": BrevoProvider(
            EmailSettings(
                api_key=brevo_key,
                from_email=sender_email,
                from_name=sender_name,
            )
        ),
        "resend": ResendProvider(
            EmailSettings(
                api_key=resend_key,
                from_email=sender_email,
                from_name=sender_name,
            )
        ),
    }
)
```

Passing registered_providers replaces the defaults; include ConsoleProvider and
FakeSmsProvider explicitly if desired. API keys are SecretStr fields and excluded
from settings repr. Never log them or raw service responses.

### Create an email template

Both providers accept the same definition: required subject and text strings,
and optional html. Patterns use $name, ${amount}, etc. Non-null recipient identity
fields override shared facts; all other values come from facts. Use $$ for a
literal dollar sign. Substitution is one pass, with no expressions or evaluation.

```json
{
  "label": "email_receipt",
  "definition": {
    "subject": "Payment receipt for $name",
    "text": "Hello $name, received $amount. Reference: $reference",
    "html": "<p>Hello $name, received <strong>$amount</strong>.</p><p>Reference: $reference</p>"
  }
}
```

POST this to /v1/templates. Substituted HTML values are escaped; the HTML template
itself is authored/trusted application content. If html is absent, a safe HTML
representation of the text is generated. Resend receives HTML and text alternatives.
Brevo receives the prepared HTML body, following its documented one-body-type
request form. Subjects must not contain newlines.

Template registration is optional for these inline email adapters. Registering
validates the definition and stores revision/fingerprint metadata in the kit;
it does not create a hosted Brevo/Resend template. Updating/unregistering operate
on that inline registration. Hosted vendor template CRUD is not implemented here.

### Submit an email

```json
{
  "provider": "resend",
  "template": "email_receipt",
  "recipients": [
    {"username": "alice", "name": "Alice", "email": "your-test-recipient@example.com"}
  ],
  "facts": {"amount": 500, "reference": "PAY-123"},
  "idempotency_key": "resend-payment-123"
}
```

POST to /v1/notifications, then explicitly POST /v1/worker/run-once. Use provider
brevo and a new request key to exercise Brevo. Choose a real recipient you control;
the worker makes real email API calls when keys are configured. No outbound sends
were performed while implementing these adapters.

### Outcomes and retries

- Missing/invalid email fails only that recipient during preparation.
- Successful vendor responses store the vendor message ID and accepted status.
- HTTP 429 and safe connection-establishment failures are temporary failures.
- Vendor rejection (for example authentication or invalid content) is permanent.
- Read/write failures, HTTP 408 and server errors are uncertain: unknown, without
  automatic resend. A success response without a message ID is also unknown.
- Safe code/message strings are retained, bounded and with this instance's key
  redacted. Unexpected exception contents and raw responses are not exposed.

Each delivery ID is passed as vendor idempotency key. Resend uses the HTTP
Idempotency-Key header; Brevo uses headers.idempotencyKey in its JSON body.
Their deduplication windows are vendor-limited; they are not an exactly-once
promise. Recipient entries remain independent even if their addresses match.

These email adapters do not implement vendor confirmation or consume webhooks.
Their accepted results are terminal acceptance, not proof of delivery. The kit
supports polling for providers declaring supports_delivery_status=True and
reconciles unknown/expired leases without blind resend. Uncertain jobs block
template mutation until their deadline or confirmed outcome. Use a new label if
an existing template remains in use. Offline transport and content tests cover
these adapters; live credentials/sender verification is a separate manual check.

References used for the HTTP adapters:

- [Resend send email](https://resend.com/docs/api-reference/emails/send-email)
- [Resend idempotency](https://resend.com/changelog/idempotency-keys)
- [Brevo transactional email](https://developers.brevo.com/docs/send-a-transactional-email)
- [Brevo idempotency](https://developers.brevo.com/changelog/2021/11/10)
