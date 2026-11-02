# Provider contract

A registration name identifies one application-owned provider instance. It can
handle any number of templates. The linkage key is (template_label, provider),
not one template per provider registration. Metadata is a JSON object interpreted
by the provider; the kit separately tracks the linked local revision.

## Recipients

Recipient contains required username and optional name, email and phone.
In-app/push implementations use username to call application services; email
providers require email; SMS/WhatsApp providers require phone. validate_recipient
must raise ProviderError with RECIPIENT_INVALID and a safe detail if required
contact information is absent or invalid. The default validates username only.

There is no recipient deduplication. Every input position produces an independent
job, even for identical usernames or contacts. Providers must prepare recipient
specific content as appropriate; the console example exposes recipient fields as
placeholders, with non-null recipient attributes overriding shared facts.

Submission idempotency is separate: replaying an identical request with the same
idempotency key returns the original IDs. To request another delivery use a new
request key. A provider receives a different delivery key for each recipient job.

## Template lifecycle

1. templates.create/update stores caller content. Each edit increments revision.
2. template_register explicitly registers one label with one provider. It may
   submit for approval or link an existing approved reference described in the
   definition. Returned metadata is stored even if approval is pending.
3. template_status(refresh=True) checks current linked metadata; send also checks
   linked templates before preparing jobs. No linkage means no registration
   check: the provider may attempt delivery or report its required-registration
   error. Empty metadata still means a link exists.
4. Editing does not silently synchronize external resources. template_update calls
   update_template with the current definition and previous metadata. A provider
   may edit, create a version, or report manual action/unsupported operation.
   Stale revisions are blocked from new sends until explicitly synchronized.
5. template_unregister calls unregister_template and removes linkage only after
   confirmation. No external removal step is needed for providers like console,
   but they still implement this method. Pending/unsupported/failed removal
   raises ProviderError and retains linkage.
6. templates.delete requires no linkage rows and no unfinished deliveries. It
   does not silently delete external resources or discard their IDs.

Template edit, register, update, unregister and delete are conservatively blocked
while ANY provider has unfinished deliveries for that label, including accepted
or unknown outcomes. This avoids invalidating a prepared external reference.
Use a new template label if an existing one remains in use.

The lifecycle gate persists across network calls; provider calls do not hold a
SQL transaction. Submission rechecks revision/linkage while committing jobs to
close preparation races. A process killed during lifecycle mutation can leave
operation_token set. Use template_recover with the same operation only after
confirming its original owner stopped. The provider must reconcile the repeated
operation key; recovery is an explicit operator action, not concurrent takeover.

Provider register/update/delete must reconcile repeated operation keys. A remote
change and the kit's SQLite/PostgreSQL commit are not one atomic transaction.
A payload snapshot does not freeze a provider's externally editable resource;
version references should be used where supported. Manual external changes remain
outside the kit's control.

## Gateway-specific behavior

Approval, language codes, approved-template components, DLT references, sender
headers, gateway template IDs and parameter mappings belong to the provider's
schema and implementation. The notifier does not implement gateway conditionals.
Registration is not a guarantee of approval. A plugin unable to perform an action
can report UNSUPPORTED_OPERATION or PROVIDER_ACTION_REQUIRED. A check awaiting
approval returns available=False with TEMPLATE_PENDING and diagnostic text.
Concrete gateway adapters are not included in this change.

## Standard errors

```python
raise ProviderError(
    "phone is required for this provider",
    code=ErrorCode.RECIPIENT_INVALID,
)
```

NotifierError exposes code, detail, provider and operation. The code is a stable
kit enum; detail is the provider-authored diagnostic string, without credentials,
authorization headers or raw service responses. Unexpected provider exceptions
are replaced with generic safe diagnostics. No string parsing is required.

Preparation/recipient failures persist as individual failed jobs with error_code
and reason; other recipients continue. ProviderResult likewise supports an
error_code with its reason and retry classification. Network uncertainty is not
authorization to retry. Lifecycle/preflight failures raise NotifierError before
jobs are queued. HTTP error translation is the example application's responsibility.

## Database upgrade note

Recipient fields, error_code, linked revision and lifecycle gates change the
schema. initialize checks the migration revision marker and missing columns; it does not
create or migrate an older database. Application Alembic owns schema upgrades. It reports SCHEMA_MISMATCH rather than silently losing
history. Preserve existing data and supply a fresh database for manual review, or
perform an explicit migration. Packaged Alembic migrations are integrated by the application; adoption of historical draft data remains explicit.

## Delivery confirmation and completion

Set supports_delivery_status=True when the provider implements confirmation. An
accepted result then schedules checks; return DELIVERED for confirmation,
PERMANENT_FAILURE for known rejection, or UNKNOWN when a lookup cannot establish
the outcome. A check returning TEMPORARY_FAILURE explicitly establishes that no
delivery happened and authorizes a new send. Do not use that classification for
a lookup outage. Stable delivery idempotency keys are reused only for the same job.

Providers without confirmation finish at accepted without inventing delivered.
Unknown/interrupted sends reconcile until their configured deadline, then finish
as terminal unknown. Callbacks must inspect both status and terminal. The worker
uses fenced leases and operation timeouts. Provider methods must be cancellation
cooperative and avoid blocking the event loop. Work that ignores cancellation is
outside the timeout contract; exactly-once external effects cannot be guaranteed.
