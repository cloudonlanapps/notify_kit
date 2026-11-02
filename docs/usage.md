# Usage guide

notify_kit stores templates and delivery jobs, invokes registered providers, and
tracks each recipient independently. Your application supplies provider instances,
chooses recipients and schedules the worker.

## 1. Install and prepare the database

```bash
uv add notify-kit
# If using PostgreSQL instead of SQLite:
uv add 'notify-kit[postgres]'
```

Include the kit's packaged revisions in your application's Alembic configuration,
then run the application migrations before starting servers or workers:

```bash
uv run alembic upgrade heads
```

See [migration setup](README.md#application-owned-alembic-migrations) for the
alembic.ini and env.py changes. Notifier initialization checks compatibility; it
does not create tables or apply upgrades.

## 2. Create the notifier

Construct your providers with their required credentials and application services.
Register them under stable names. One provider can handle many templates, and the
same provider implementation can have several configured instances.

```python
from notify_kit import (
    Notifier, NotifyProvider, RetryPolicy, WorkerPolicy, RetentionPolicy, SQLiteStorage,
)


async def create_notifier(provider: NotifyProvider) -> Notifier:
    storage = SQLiteStorage("notifications.db")
    notifier = Notifier(
        storage=storage,
        providers={"primary": provider},
        retry_policy=RetryPolicy(
            max_attempts=5,
            initial_delay_seconds=60,
            max_delay_seconds=3600,
        ),
        worker_policy=WorkerPolicy(
            max_age_seconds=24 * 60 * 60,
            status_poll_seconds=60,
            operation_timeout_seconds=30,
            lease_seconds=60,
            time_budget_seconds=10,
        ),
        retention_policy=RetentionPolicy(
            acknowledged_seconds=24 * 60 * 60,
            unacknowledged_seconds=30 * 24 * 60 * 60,
            callback_max_attempts=5,
            callback_retry_seconds=60,
            callback_deadline_seconds=24 * 60 * 60,
        ),
    )
    try:
        await notifier.initialize()
    except BaseException:
        await storage.aclose()
        raise
    return notifier
```

Here, provider is your application-owned NotifyProvider implementation. It can
invoke an in-app module, a push service or an external messaging gateway. See
[the provider contract](provider_contract.md) for its methods and error handling.

For PostgreSQL, replace SQLiteStorage with:

```python
from notify_kit import DatabaseStorage

storage = DatabaseStorage(
    url="postgresql+asyncpg://user:password@host:5432/database",
)
```

Use the same database URL for application migrations and runtime. After an
application restart, register the same provider names against the same database.

The remaining snippets run inside your application's async functions, using the
notifier returned above.

## 3. Manage templates

Templates have unique labels. Their definition is JSON-compatible data whose
format is defined by the selected provider; notify_kit does not impose a universal
body syntax or render it itself.

```python
await notifier.templates.create(
    label="payment_receipt",
    definition={"body": "Hello $name, payment received: $amount"},
)

stored = await notifier.templates.get("payment_receipt")
all_templates = await notifier.templates.list()
```

This body syntax matches the repository's example console provider. For another
provider, supply the definition its implementation expects, such as an approved
template reference and parameter mapping.

If the provider needs template registration:

```python
metadata = await notifier.template_register(
    provider="primary",
    template="payment_receipt",
)

# Query the provider and persist refreshed metadata.
metadata = await notifier.template_status(
    provider="primary",
    template="payment_receipt",
    refresh=True,
)
```

Registration may start approval rather than finish it. Metadata belongs to the
provider. An unavailable or pending template produces a standard error when
verified; follow its diagnostic and check again later.

If no linkage exists, send skips registration verification and lets the provider
prepare the request. An empty metadata object still counts as an existing link.

## 4. Submit notifications

```python
from notify_kit import Recipient

receipt = await notifier.send(
    provider="primary",
    template="payment_receipt",
    recipients=[
        Recipient(username="alice", name="Alice", email="shared@example.com"),
        Recipient(username="bob", name="Bob", email="shared@example.com"),
    ],
    facts={"amount": 500},
    idempotency_key="payment-123-receipt",
)

batch_id = receipt.batch_id
for delivery in receipt.deliveries:
    print(delivery.id, delivery.recipient.username)
```

send commits jobs before returning IDs. It queues work; it does not deliver it.
Facts are shared across this submission. The provider decides how recipient
attributes are incorporated into its prepared content.

Every recipient needs username. name, email and phone are optional in the common
model. Each provider validates what it needs: in-app/push can use username, email
providers need email, and SMS/WhatsApp providers need phone.

There is no recipient deduplication. The two entries above remain separate jobs,
even though they share an email address.

Reuse the idempotency key only when repeating the same request, such as after a
lost response. An identical replay returns existing IDs. Different input with the
same key is rejected. A deliberate new notification needs a new key. Idempotency lasts only while its
records are retained. After partial recipient cleanup, replay returns
idempotency_expired rather than a misleading partial receipt or a new send. Once
the entire batch is removed, the key is no longer reserved.

## 5. Schedule the worker and query status

Have your application's scheduler invoke this periodically:

```python
updated_deliveries = await notifier.run_once(max_jobs=100)
```

Each invocation processes due attempts and returns. Temporary failures are
scheduled for later attempts according to policy; the worker does not sleep until
the next retry. Permanent failures are not automatically retried. Keep scheduling
invocations so due retries are processed.

Query one recipient or the entire batch:

```python
delivery = await notifier.get_status(receipt.deliveries[0].id)
print(delivery.status, delivery.error_code, delivery.reason)

for delivery in await notifier.get_batch(batch_id):
    print(delivery.recipient.username, delivery.status)
```

Persist the returned IDs in your application if needed. These queries also work
after restart. accepted means the provider accepted the request; it does not
necessarily mean delivered. Check terminal to know whether the lifecycle finished.
Providers without delivery confirmation complete at accepted; providers declaring
supports_delivery_status=True are polled until confirmation or the age deadline.
unknown is an uncertain outcome, not a safe signal to submit another notification.
It reconciles without a blind resend and becomes terminal unknown at its deadline. A missing record likewise does not prove that
nothing was sent.

## 6. Handle errors

Request-wide failures raise NotifierError:

```python
from notify_kit import NotifierError

try:
    await notifier.template_status(
        provider="primary", template="payment_receipt", refresh=True,
    )
except NotifierError as error:
    print(error.code, error.detail, error.provider, error.operation)
```

Use code for application decisions and detail for diagnostics. Providers supply
safe diagnostic strings; unexpected exception contents are not exposed.

Recipient validation/preparation errors do not reject the whole batch. send
returns IDs normally; the affected job is already failed with zero attempts.
Query its error_code and reason. Other recipients continue. Delivery-time failures
are also stored per recipient. Check statuses even when send returned successfully.

## 7. Edit or remove a template

Wait until the template has no unfinished deliveries before changing its lifecycle.

```python
await notifier.templates.update(
    label="payment_receipt",
    definition={"body": "Hello $name, confirmed payment: $amount"},
)

# Synchronize each existing provider link explicitly.
await notifier.template_update(provider="primary", template="payment_receipt")
```

A local edit increments the revision. Linked providers must be synchronized before
new submissions can use it. The provider handles editing/versioning and approval.
Unsupported operations or required manual actions are reported through errors.

To remove a template, unregister every linked provider first:

```python
await notifier.template_unregister(provider="primary", template="payment_receipt")
await notifier.templates.delete("payment_receipt")
```

Unregister removes linkage only after provider confirmation. Local deletion does
not silently delete external resources. Active or uncertain deliveries block
lifecycle changes; use a new label if the existing template is still in use.

## 8. Completion callbacks, acknowledgement and cleanup

Pass an async completion handler when constructing Notifier:

```python
from notify_kit import CompletionEvent


async def on_completed(event: CompletionEvent) -> None:
    # Save to your application DB using event.id as an idempotency key.
    # Inspect event.delivery.status: accepted is not confirmed delivery.
    print(event.id, event.delivery.id, event.delivery.status)


notifier = Notifier(
    storage=storage,
    providers={"primary": provider},
    completion_handler=on_completed,
)
await notifier.initialize()
```

The worker creates a persisted event atomically with each terminal delivery,
including preparation failures. Callback exceptions schedule independent retries;
they never resend a notification. Handlers may run more than once after a crash,
so make application updates idempotent using event.id. Configure the handler again
after restart. If none is supplied, callback handling is intentionally disabled
and the worker marks completion events handled without invoking application code.

```python
completion = await notifier.get_completion(delivery_id)
print(completion.status, completion.attempts, completion.reason)
```

Exhausted callbacks remain failed and queryable until retention cleanup. Their
exception contents are not exposed. Use this status for operator follow-up.
After saving a terminal outcome in your application, acknowledge that recipient:

```python
await notifier.acknowledge(delivery_id)
```

Queries do not acknowledge automatically. The scheduled worker also runs bounded
cleanup: defaults retain acknowledged results for 24 hours and unacknowledged
results for 30 days. Pending callbacks hold records until handling succeeds or its
deadline is exhausted. Prepared content is cleared once callback handling stops;
status remains queryable until expiry. Templates are not deleted by job cleanup.
Stop running workers for too long and both retries and cleanup will be delayed.

Expired send leases are reconciled before any resend. Interrupted template
mutations require an operator to confirm the original owner has stopped, then
repeat the same operation with its stable provider operation key:

```python
from notify_kit import TemplateOperation

await notifier.template_recover(
    provider="primary", template="payment_receipt",
    operation=TemplateOperation.REGISTER,  # The operation that was interrupted.
    confirmed_stopped=True,
)
```

Providers must reconcile repeated register/update/unregister operation keys. Never
use this recovery API to take over a still-running call or process.

## 9. Command line

The CLI uses an application-owned provider factory; it does not load secrets or
run migrations implicitly. A factory is a synchronous module:callable returning
named NotifyProvider instances. For example, from the FastAPI example directory:

```bash
uv run notify-kit --database-url sqlite+aiosqlite:///example_notifications.db \
  --factory app.providers.factory:build_providers send \
  --provider fake_sms --template sms_receipt \
  --recipients '[{"username":"alice","phone":"+919876543210"}]' \
  --facts '{"amount":500}' --idempotency-key sms-example-1

uv run notify-kit --database-url sqlite+aiosqlite:///example_notifications.db \
  --factory app.providers.factory:build_providers worker --max-jobs 100
```

Create/register the template through your application first. The preview command
uses --recipient for one JSON object instead of --recipients and needs no request
key. status --delivery-id ID queries a persisted delivery. Results are JSON; a
request-wide error writes structured JSON to stderr and exits with status 2.

## 10. Shut down

Always call await notifier.aclose() after stopping worker invocations and allowing
active work to finish. Use try/finally so cleanup also runs when application work
raises an exception:

```python
notifier = await create_notifier(provider)
try:
    # Run your application and schedule worker invocations here.
    ...
finally:
    # Stop scheduling and await active worker calls before closing storage.
    await notifier.aclose()
```

For FastAPI, put cleanup in the lifespan's finally block. The example server does
this by closing its storage instance, which releases the same database resources.
Your application must also close provider clients and services it owns.

**If aclose() never executes:** pooled database connections and SQLite background
threads can remain allocated while the process is alive. Repeatedly creating
notifiers without closing them can accumulate those resources. On process exit,
the operating system closes connections, but asynchronous cleanup may emit warnings
or event-loop-closed errors. Process exit is not a substitute for explicit cleanup.

Committed templates and delivery jobs remain persisted even if aclose() is not
called; it is resource cleanup, not a save operation. It does not drain the queue,
finish active sends, or recover interrupted jobs. If the process stops during a
provider call, a delivery may remain processing with an uncertain outcome; closing
storage does not establish whether the provider delivered it.

For a runnable HTTP integration with Pydantic schemas and Swagger UI, see the
[FastAPI example](examples/fastapi_server/README.md).
