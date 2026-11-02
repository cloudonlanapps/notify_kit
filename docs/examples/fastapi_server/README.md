# notify_kit FastAPI example

A separate uv project that consumes the root package as an editable dependency.
The default startup includes console and fake_sms; Brevo/Resend are enabled with
explicit startup credentials. See [provider setup and walkthroughs](providers.md).

Routers are thin, Pydantic request/response schemas live in schemas/ (one class per
file), and services adapt the public kit API. Provider instances are constructed
at startup, not accepted as arbitrary Python code through HTTP.

## Run

From the repository root:

```bash
cd examples/fastapi_server
uv sync
uv run alembic upgrade heads
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open [Swagger UI](http://127.0.0.1:8000/docs) or
[OpenAPI JSON](http://127.0.0.1:8000/openapi.json). The lifespan starts notifier.run_forever() automatically and waits for it during
shutdown. POST /v1/worker/run-once is also available for manual processing.
Worker failures are logged immediately; they also propagate when lifespan awaits
the task on shutdown. This example does not automatically restart failed workers.
Pass start_worker=False to create_app for scheduler-driven integration or tests. The SQLite file
example_notifications.db is relative to the working directory. Restarting with
the same file preserves templates, registrations and delivery status.

The example exposes administrative operations without authentication for local
manual use. Console output is written to the Uvicorn log; it sends no email or push.

## Walkthrough

Create a template. Console syntax uses $name or ${name}; substituted values are
literal text, not markup. This syntax belongs to this example provider, not the kit.

```bash
curl -sS http://127.0.0.1:8000/v1/templates \
  -H 'Content-Type: application/json' \
  -d '{"label":"payment_receipt","definition":{"body":"Hello $name, received $amount"}}'
```

Inspect providers and templates:

```bash
curl -sS http://127.0.0.1:8000/v1/providers
curl -sS http://127.0.0.1:8000/v1/providers/console
curl -sS http://127.0.0.1:8000/v1/templates
curl -sS http://127.0.0.1:8000/v1/templates/payment_receipt
```

Optional registration and verification:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/templates/payment_receipt/providers/console/register
curl -sS http://127.0.0.1:8000/v1/templates/payment_receipt/providers/console
curl -sS -X POST http://127.0.0.1:8000/v1/templates/payment_receipt/providers/console/refresh
```

If there is no registration row, status metadata is null and submission skips
verification. Registration persists the console provider's revision metadata.
Editing a linked template makes its linkage stale until explicitly updated using PUT /v1/templates/{label}/providers/{provider}.

Submit a batch:

```bash
curl -sS http://127.0.0.1:8000/v1/notifications \
  -H 'Content-Type: application/json' \
  -d '{"provider":"console","template":"payment_receipt","recipients":[{"username":"alice","name":"Alice","email":"shared@example.com"},{"username":"bob","name":"Bob","email":"shared@example.com"}],"facts":{"name":"Customer","amount":500},"idempotency_key":"payment-123"}'
```

Copy the returned batch_id and individual delivery IDs. Before worker execution,
statuses initially are queued, then the background worker processes them. Repeating the same request/key returns the same IDs; changing
inputs with that key produces a conflict. All recipients share the supplied facts. Console placeholders also include username, name, email and phone. Non-null recipient fields override shared facts. The two entries above are both delivered; there is no recipient deduplication.

```bash
curl -sS http://127.0.0.1:8000/v1/notifications/batches/BATCH_ID
curl -sS http://127.0.0.1:8000/v1/notifications/deliveries/DELIVERY_ID
curl -sS http://127.0.0.1:8000/v1/worker/run-once \
  -H 'Content-Type: application/json' -d '{"max_jobs":100}'
```

Query those IDs again, including after restarting the server. For console,
`delivered` means the console operation finished, not external email delivery.

After deliveries finish, edit, synchronize, unregister and delete:

```bash
curl -sS -X PUT http://127.0.0.1:8000/v1/templates/payment_receipt \
  -H 'Content-Type: application/json' \
  -d '{"definition":{"body":"Payment confirmed: $amount"}}'
curl -sS -X PUT http://127.0.0.1:8000/v1/templates/payment_receipt/providers/console
curl -sS -X DELETE http://127.0.0.1:8000/v1/templates/payment_receipt/providers/console
curl -sS -X DELETE http://127.0.0.1:8000/v1/templates/payment_receipt
```

Updates/removal require no unfinished jobs. Local deletion also requires all provider links removed. Existing completed delivery records retain their snapshots and status.

## Custom providers and PostgreSQL

Supply application-owned provider instances to create_app(registered_providers=...).
They implement NotifyProvider; no router changes are needed. Keep credentials in
startup configuration, not HTTP requests. Console reports successful output; fake_sms requires internal template registration
and prints messages with phone destinations. Brevo/Resend adapters report real
transport outcomes when explicitly configured. No adapter injects artificial
network failures.

For PostgreSQL install the optional driver:

```bash
uv sync --extra postgres
```

Create a small launcher module alongside app/main.py and call create_app with an
explicit URL, then use its module path with Uvicorn:

```python
from app.main import create_app

app = create_app(database_url="postgresql+asyncpg://user:password@host/database")
```

Application Alembic creates/upgrades kit tables before startup. Notifier initialization only checks compatibility; it never changes the schema. Use the SAME URL in Alembic and your create_app launcher. The existing raw/create_all draft needs explicit conversion or a fresh database.

## Current scope

Every currently implemented notifier operation is exposed, with lifecycle
initialization/cleanup handled by FastAPI lifespan. Database/provider errors use
structured code/detail responses. Request schema validation returns HTTP 422.

The example exposes preview, completion queries, acknowledgement and explicit
interrupted-template recovery. Worker invocations handle due sends/status checks,
completion callbacks and bounded cleanup. create_app accepts retry_policy,
worker_policy, retention_policy, completion_handler and start_worker constructor arguments.

Offline HTTP/provider tests live in the root tests/ directory. No real messages
are sent by automated tests. Acceptance-only email adapters produce terminal
accepted results, not delivered; confirmation-capable plugins opt into polling.

## Recipient and lifecycle API changes

Recipient JSON now requires username; name/email/phone are optional. Missing contact
requirements are validated by each provider. Individual preparation errors appear
as failed delivery statuses with error_code and reason; other entries continue.

The error response includes code/detail and optional provider/operation. Explicit
provider details are preserved; arbitrary exception and database contents are not.

Existing example databases need migration for this schema change. No old database
has been deleted or modified as part of the code update. To manually review with a
fresh database, use a launcher calling create_app(database_url="sqlite+aiosqlite:///example_v2.db").
Initialization detects missing columns and explains SCHEMA_MISMATCH. A killed
lifecycle operation can leave a persistent busy gate requiring reconciliation;
use the explicit confirmed-owner-stopped recovery API before repeating the same mutation.

## Migration setup

This project has an application-owned alembic.ini and alembic/env.py. Its versions/
contains the empty app_0001 baseline; the kit supplies nk_0001, nk_0002 and nk_0003 on the independent
notify_kit branch. Both share alembic_version. Run from this example directory:

```bash
uv sync
uv run alembic upgrade heads
uv run uvicorn app.main:app --reload
```

The migration URL defaults to the same app.constants.DEFAULT_DATABASE_URL as the
server. For a custom URL, configure sqlalchemy.url in alembic.ini (escape literal
percent characters as %% in INI values) or supply config.attributes["database_url"]
from your application's Python deployment function. A custom create_app URL must
match it. Credentials need not be committed; explicit Python configuration can
supply a SQLAlchemy URL object via config.attributes.

To create an application-owned migration:

```bash
uv run alembic revision --autogenerate --head app@head \
  --version-path alembic/versions -m "application change"
```

Do not use upgrade head or generate into the installed package. Package table
filters prevent accidental kit changes in application revisions. No migrations
run in lifespan. Startup fails with SCHEMA_MISMATCH when deployment was skipped.

For existing unversioned example tables, migration cannot automatically adopt
historical data. Use a fresh database or perform an explicit audited conversion;
do not stamp an unchecked schema. No existing example database was removed by
this change. See docs/README.md's application integration instructions for full
setup, async Python invocation, existing-data handling and rollback limits.

## Completion and retention endpoints

- POST /v1/notifications/preview prepares one recipient without queueing.
- GET /v1/notifications/deliveries/{id}/completion reports callback handling.
- POST /v1/notifications/deliveries/{id}/acknowledge records application acknowledgement.
- POST /v1/templates/{label}/providers/{provider}/recover takes operation and
  confirmed_stopped=true, after an operator confirms the interrupted owner stopped.

Terminal results remain queryable under the configured retention policy. Queries
do not acknowledge them. A missing ID is not proof that nothing was sent. See the
root usage guide for policies, completion handler registration and shutdown.
