# notify_kit requirements

This is the agreed provider-based contract for issue #1. It supersedes the original
channel-routing, recipient-deduplication and kit-owned rendering proposal.

Each rule has a dedicated pytest test marked `@pytest.mark.requirement("Rn")`.
[✅] means implemented and covered; [GAP] means outstanding. The coverage guard
checks collected tests, rejects unknown IDs, and requires evidence for completed
rules. Runtime coverage and migration/schema tests complement these markers.

## Independence and providers

- **R1** [✅] Caller-owned routing and business policy stay upstream; the kit accepts opaque usernames and explicitly named providers.
- **R2** [✅] Configuration and storage URLs are explicit. Runtime initialization checks migrations without creating or altering tables.
- **R3** [✅] Network delivery/registration/status work belongs to provider operations; local construction/configuration checks perform no network I/O.
- **R4** [✅] The Python >=3.12 package builds wheel/sdist artifacts, ships migrations and typing metadata, uses uv, passes strict checking, and has offline tests.
- **R5** [✅] Applications register externally implemented provider instances under stable names.
- **R6** [✅] Multiple provider instances coexist; every submission selects exactly one by name.
- **R7** [✅] Credentials and sender identity belong to individual provider instances, not SDK globals.
- **R8** [✅] Invalid configuration and policy values fail with safe standard errors; configuration validity is distinct from remote availability.
- **R9** [✅] Unknown providers fail before submission. Existing jobs survive missing registrations after restart and expose an actionable error. No linkage skips template checks; empty linked metadata does not.
- **R10** [✅] The FastAPI example provides a credential-free console provider and typed endpoints for manual use.
- **R11** [✅] Application-local in-app/push modules and external services implement the same provider abstraction; no separate channel registry exists.
- **R12** [✅] Offline doubles exercise success, permanent/transient failure, uncertainty and status lookup independently per recipient.
- **R13** [✅] Prepared jobs omit provider configuration. Unexpected exceptions are replaced with safe diagnostics; providers supply safe detail strings and standard codes.

## Templates and preparation

- **R14** [✅] The kit supplies SQLAlchemy template/job storage for SQLite and PostgreSQL; template definitions persist until explicitly removed.
- **R15** [✅] Template CRUD supports unique labels, retrieval/listing, complete replacement with revision increment and deletion.
- **R16** [✅] One provider supports many template linkage rows, each storing opaque metadata and the linked revision.
- **R17** [✅] Duplicate/missing records fail explicitly. Unregister is confirmed before linkage removal; deletion requires no links or active jobs. Edits require explicit provider synchronization. Interrupted mutations have an explicit confirmed-owner-stopped recovery operation.
- **R18** [✅] Provider registration validates provider-specific definition/placeholder syntax; the generic store does not impose a universal schema.
- **R19** [✅] Example email providers accept subject/text and optional HTML with literal substitutions, matching their inline-send APIs.
- **R20** [✅] Providers may manage approved references and ordered parameters. The fake SMS example requires a persisted internal template registration and prints the phone/message instead of delivering externally.
- **R21** [✅] Definitions can carry provider-owned push/in-app title/body/data without core interpretation.
- **R22** [✅] Providers prepare serializable personalized payloads; submission snapshots them before persistence and retries reuse the snapshot.
- **R23** [✅] Example email substitutions escape HTML fact values and do not interpret inserted values as markup or expressions.
- **R24** [✅] Layout/content is provider-owned definition data. The kit invents no branding; example text-only email produces safe HTML without requiring a logo.
- **R25** [✅] Missing required facts prevent delivery for the affected recipient and include the fact name in a safe diagnostic.
- **R26** [✅] Example renderers ignore unused facts rather than leaking them into messages.
- **R27** [✅] Applications choose exact template labels; translation and language fallback are not core responsibilities.
- **R28** [✅] Preview uses the same provider preparation without enqueueing or sending, and is exposed by the example API.

## Submission and delivery

- **R29** [✅] send commits a batch and one ordered delivery ID per input recipient before returning.
- **R30** [✅] Async provider/storage work leaves the caller's event loop available.
- **R31** [✅] Providers validate required username/email/phone fields. Validation/preparation errors become individual failed jobs with zero delivery attempts; other recipients continue.
- **R32** [✅] One recipient's failure, including malformed plugin output, does not abort others. Successful recipients are never retried because another fails.
- **R33** [✅] Status queries survive restart and include provider/message ID, attempts, timestamps and next due time. Identical whole-request idempotency replays return existing IDs; changed input conflicts.
- **R34** [✅] No recipient deduplication occurs, even for identical usernames or contacts. Request idempotency is a separate concept.
- **R35** [✅] Empty batches create no recipient jobs and perform no delivery calls.
- **R36** [✅] Configurable retry/backoff/age limits stop permanent failures and bound temporary failures. Unknown outcomes reconcile before resend. Acceptance and confirmed delivery remain distinct; unsupported confirmation is never invented.
- **R37** [✅] Jobs/status/counters, leases and completion events persist in SQLAlchemy storage; migrations preserve previously versioned data.

## CLI and worker lifecycle

- **R38** [✅] The CLI can submit and process jobs using an explicitly supplied application provider factory and database URL, returning JSON results/errors.
- **R39** [✅] The CLI can preview provider-specific prepared content without delivery.
- **R40** [✅] The application starts run_forever() or schedules bounded run_once() batches. Provider operations have timeouts; retries/status checks persist due times rather than sleeping.
- **R41** [✅] Database claims and lease tokens prevent concurrent ownership/stale writes. Expired send leases reconcile instead of blindly resending. Exactly-once external effects are not promised.
- **R42** [✅] Terminal success/failure and a stable completion event commit atomically, including preparation failures. Callback retries never redeliver the notification.
- **R43** [✅] Completion handling is at least once, with stable IDs, leases, bounded retries/deadlines and queryable exhaustion. Handlers are supplied again after restart.
- **R44** [✅] Queries do not acknowledge results. Explicit acknowledgement is allowed only for terminal deliveries and is independent of callback handling.
- **R45** [✅] Configurable acknowledged/unacknowledged retention preserves active work and pending callbacks. Bounded cleanup removes terminal content after callbacks stop and deletes a batch only after its delivery records are gone.
- **R46** [✅] Missing/removed IDs return not_found, never evidence that delivery did not happen.

## Defaults and semantics

All policies are constructor arguments to Notifier. Defaults: five send attempts,
60-second initial exponential backoff capped at one hour, a 24-hour maximum job
age, 60-second polling, 30-second operation timeout, 60-second leases, and a
continuous worker with no overall time budget. Callback defaults are five attempts, 60-second retry and
a 24-hour deadline. Retain acknowledged results for 24 hours and unacknowledged
results for 30 days. Policy values are validated and may be overridden per notifier.

A provider without delivery confirmation completes successfully at accepted,
without claiming delivered. A confirmation-capable provider sets
supports_delivery_status=True; accepted jobs are polled. Unknown jobs reconcile
without resend and become terminal unknown at their deadline. A status-check
TEMPORARY_FAILURE explicitly authorizes retry because the provider has established
non-delivery; lookup failures must return UNKNOWN. Callbacks receive terminal
outcomes, including accepted/unknown. No handler means completion handling is
intentionally disabled and its event is marked handled by the worker.

Applications own consent, routing, scheduling and saving returned IDs. Provider
plugins own gateway approval/DLT rules and credential-safe details. The example
contains Brevo, Resend and fake SMS; they are not bundled core adapters. Real mail
requires user-supplied verified sender settings and credentials. External approval
workflows remain provider-specific rather than being simulated by the kit.

The application's Alembic environment loads the packaged notify_kit branch and
runs upgrade heads. Startup is read-only. Unversioned pre-migration draft databases
need explicit audited conversion or deliberate replacement; they are never silently
stamped. PostgreSQL uses an existing database/schema/search path. Applications must
stop scheduling and finish active work before closing the notifier.
