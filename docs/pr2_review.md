# Review: PR #2 — Implement notify_kit with persistent delivery and provider plugins

Branch `codex/1-notifier-provider-foundation` against `main`. This review covers
`src/notify_kit`, the migrations, the CLI, the example server and the test suite.
Findings are ranked from most to least severe. The reviewer did not run any of
these scenarios; each one comes from reading the code.

## Correctness

1. **`src/notify_kit/services/worker.py:100`: a send cut short by the time budget becomes a permanent UNKNOWN, so the message is never sent.**

   **Resolution:** Fixed with the agreed run_forever(stop=...) design and FastAPI lifespan integration. Removed the overall time budget; run_once bounds job counts and each operation gets its full timeout. Slow claims and successive sends have regression coverage.

   `remaining` is computed before the `claim()` transaction. The send then runs under `asyncio.timeout(min(remaining, operation_timeout))`.
   If the budget is nearly used up, or the claim itself took longer than what was left, the timeout is about 0 or negative. The provider's first `await` is cancelled before any request goes out, and the `TimeoutError` is recorded as `UNKNOWN` with `attempts=1`.
   From then on the job is a reconcile job, which never resends. For a provider without delivery status it stays UNKNOWN until `max_age`, then ends as terminal UNKNOWN. The message is silently never sent.
   Fix: stop claiming new send work when `remaining` is below a minimum (for example `operation_timeout_seconds`). Alternatively, re-check after the claim and release the claim unattempted.

2. **`src/notify_kit/storage/completion_store.py:71` together with `services/worker.py:198`: one exhausted completion event stops all callback dispatch for that run.**

   **Resolution:** Fixed. An exhausted claim returns the failed event with no lease token. Dispatch counts it against its bounded batch and continues rather than treating exhaustion as an empty queue. Regression: expired final handler lease followed by a dispatchable event.

   When the event `claim()` picks has run out of attempts or passed its deadline, `claim()` marks it FAILED and returns `None`. `_dispatch` reads `None` as "no work" and `break`s.
   This happens to any event whose handler lease expired on its last attempt, or that is past its deadline. Other due PENDING events wait until the next `run_once`. With several such events, each run handles at most one of them before stopping.
   Fix: return a sentinel and continue the loop, or loop inside `claim()` until it finds a dispatchable row.

3. **`src/notify_kit/services/worker.py:174`: a status lookup that returns UNKNOWN or raises changes an ACCEPTED delivery to UNKNOWN.**

   **Resolution:** Fixed. Inconclusive reconciliation preserves prior ACCEPTED status and message ID, including lookup exceptions and the confirmation deadline. Explicit delivered/failure outcomes retain their contract; acceptance is not relabelled as delivery.

   The state is set to `ACCEPTED if result.status == ACCEPTED else UNKNOWN`. A `supports_delivery_status=True` provider can have an accepted job polled while the provider's lookup API is down. In that case `check_delivery` returns UNKNOWN, as the contract requires, or raises, which `_attempt` maps to UNKNOWN.
   The row then changes from `accepted` to `unknown`. `previous_status` becomes UNKNOWN, so the deadline path in `_attempt` (line 82) ends the job as terminal UNKNOWN even though the provider accepted the message.
   Fix: when the previous status is ACCEPTED and the check returns UNKNOWN, keep ACCEPTED.

4. **`src/notify_kit/migrations/versions/nk_0002_worker_lifecycle.py:59`: after the upgrade, existing `accepted` rows are polled and turn into `unknown`.**

   **Resolution:** Fixed in the worker, where capabilities are known. An accepted reconcile job without status support becomes terminal ACCEPTED without calling the unsupported API. A real nk_0001-to-head migration regression covers accepted rows and recipient_count.

   The migration sets `next_attempt_at` on accepted rows but leaves them non-terminal. For an email provider without status support (`supports_delivery_status=False`), the worker claims the row as a reconcile job and calls the default `check_delivery`, which returns UNKNOWN. Because of finding 3, the row becomes `unknown`, gets polled for 24 hours, then ends as terminal `unknown`.
   Accepted deliveries in a migrated database are effectively relabelled. They should be marked terminal accepted when the provider cannot confirm delivery. The migration cannot know which providers those are, so the worker should handle this case: an ACCEPTED reconcile job for a provider without status support should end as terminal ACCEPTED.

5. **`src/notify_kit/migrations/versions/nk_0002_worker_lifecycle.py:81`: the backfill fires completion callbacks for every historical delivery.**

   **Resolution:** Fixed using the no-replay policy. The unreleased nk_0002 backfill marks historical terminal events HANDLED with no next attempt. Still-active accepted/unknown jobs receive events when subsequently finalized. Migration and no-callback regressions cover this. This corrects an unreleased PR revision; released migrations must remain immutable.

   Every terminal delivery from before the upgrade gets a `pending` completion event dated at `completed_at`. On the first `run_once` after the upgrade, a configured handler receives callbacks for old deliveries the application handled long ago. Events older than `callback_deadline_seconds` are marked FAILED in bulk instead.
   Either way the application sees callbacks or failures it never asked for. Backfill these events as `handled`, or document the behaviour and make it opt-in.

6. **`src/notify_kit/storage/template_links.py:104`: one shared `lifecycle_identity` per template mixes up the operation keys of different providers.**

   **Resolution:** Fixed, with context: the shared gate blocks B while A's persisted gate is held, so the literal crash sequence cannot bypass it. But a provider exception releases the gate after a potentially successful remote action, and B could then rotate A's retry key. A regression reproduces that case. nk_0003 adds persistent per-provider generation rows, including absent-link identities. B's unregister cannot alter A's key; A's own successful unregister renews its next registration key.

   `remove()` rotates the template-wide `lifecycle_identity` when any one provider unregisters. The key in `template_lifecycle.py:34` includes that identity.
   Example: `register(provider=A)` is interrupted after the remote resource was created. Before the operator runs `template_recover(A, REGISTER)`, `template_unregister(provider=B)` succeeds. Recovery then sends A a new idempotency key, so A creates a second remote template, which is the duplicate the stable key was meant to prevent.
   Fix: store the identity per `(template, provider)` on the link, or keep a separate per-provider generation row.

7. **`src/notify_kit/storage/delivery_store.py:126` with `notifier.py:177`: concurrent sends can fail with a spurious `TEMPLATE_CHANGED`.**

   **Resolution:** Fixed without interpreting opaque metadata. Kit-owned link generation tokens change on lifecycle register/update/replacement and remain stable during status refresh. Preflight persistence and enqueue check the token plus template revision. Regressions cover concurrent changing checked_at metadata and rejection of an unregister/re-register with identical metadata.

   `send()` saves the refreshed metadata from `check_template`, then `enqueue()` requires the stored metadata to equal the value it saw. Suppose a provider's check returns changing metadata, for example `checked_at`, an approval timestamp or an ETag.
   Two concurrent `send()` calls each save different metadata. The first to reach `enqueue()` then finds the other's value and fails with `TEMPLATE_CHANGED: Provider linkage changed during preparation`, though nothing material changed.
   Fix: compare the template revision only, or have the checked metadata act as a version token chosen by the provider.

8. **`src/notify_kit/storage/completion_store.py:200`: cleanup deletes empty batches right away, so empty-request idempotency stops working.**

   **Resolution:** Fixed with explicit retention. Empty batches have created_at and retain request identity for unacknowledged_seconds (default 30 days). Cleanup deletes them only after that period and bounds batch deletion. Nonempty batches disappear once their delivery records expire. Replay before and after empty-batch expiry is tested.

   An empty `send()` (R35) creates a `BatchRecord` with no deliveries. The next `run_once` cleanup deletes every batch that has no deliveries. Replaying the same idempotency key then creates a new `batch_id` instead of returning the original receipt, which breaks R33 for empty requests.
   Fix: limit the deletion to batches whose `recipient_count > 0`, or delete empty batches using their own retention time.

9. **`src/notify_kit/storage/template_store.py:42-43`: invalid template definitions are reported as `STORAGE_ERROR`.**

   **Resolution:** Fixed. Create/update validate and detach a JSON-object snapshot before a write transaction. Non-JSON values and NaN raise INVALID_REQUEST. Parameterized regressions cover NaN, datetime and set while preserving the original revision.

   `create()` and `update()` do not check that the definition is JSON. A definition containing `NaN`, a `datetime` or a set fails inside the engine's `json_serializer` (`allow_nan=False`) and raises `StatementError`. `Database.session()` turns that into `STORAGE_ERROR` ("Database operation failed"), and the example API returns 503.
   The caller is told the database is down when the input is invalid. Validate the definition with `json.dumps(..., allow_nan=False)` and raise `INVALID_REQUEST`, as `send()` does for facts.

10. **`src/notify_kit/cli.py:127`: `worker` without `--factory` changes jobs.**

    **Resolution:** Fixed. CLI send, preview and worker require --factory before storage construction or initialization. Status may omit it. A regression verifies INVALID_REQUEST and unchanged queued job/error fields when worker has no factory.

    With no factory the CLI registers no providers. `run_once` then stamps `PROVIDER_NOT_REGISTERED` on up to `max_jobs` pending jobs from every provider, and terminally fails or finalizes any expired job of any provider. Leaving out the flag looks harmless but changes the stored state. Require `--factory` for `worker`, `send` and `preview`.

11. **`src/notify_kit/notifier.py:177`: `preview()` writes to the database.**

    **Resolution:** Clarified and improved. The old contract forbade enqueue/send, not metadata refresh, so this did not itself contradict that contract. Preview now checks availability and prepares with refreshed metadata without saving it. Send and explicit status refresh still persist metadata. Preview may reject busy/stale templates or contact the provider, but does not mutate kit state. A linked-template regression verifies this.

    The `preview()` docstring promises to prepare a notification "without enqueueing or sending it". It goes through `_check_template`, which calls `links.save(...)`, so every preview of a linked template writes provider metadata. On SQLite that takes a `BEGIN IMMEDIATE` write lock. It can also fail with `TEMPLATE_BUSY` or `TEMPLATE_CHANGED`, and it adds to the conflict in finding 7.

## Efficiency, simplification and altitude

12. **`src/notify_kit/services/worker.py:174-186`: UNKNOWN jobs for providers without status support are polled for 24 hours for no benefit.**

    **Resolution:** Fixed. Providers explicitly opt into status support. Unknown/recovered-processing work without that capability waits until its maximum-age deadline, with no repeated unsupported lookups or blind resend. Unsupported accepted work finalizes immediately. Uncertain active jobs still guard template mutation until deadline intentionally. Recovery tests declare status support when expecting successful reconciliation.

    For a provider with `supports_delivery_status=False`, the default `check_delivery` always returns UNKNOWN. Each UNKNOWN or crash-recovered job is still claimed every `status_poll_seconds`, about 1,440 claim and finish transactions per job.
    During that time the job is non-terminal, so `require_no_active_jobs` blocks `templates.update/delete` and every template lifecycle operation for that template for the whole day. Schedule a single wake-up at the deadline when the provider cannot confirm delivery.

13. **`src/notify_kit/services/worker.py:49,76`: `run_once` always takes write transactions, even with nothing to do.**

    **Resolution:** Fixed for the identified maintenance work. Missing-provider reporting and cleanup use read-only eligibility checks and skip idle write transactions. Cleanup bounds empty-batch deletion by max_records and batch creation time is indexed. Actual job claims remain atomic transactions; an idle worker still performs database reads. Storage regressions verify idle maintenance has no BEGIN IMMEDIATE/UPDATE/DELETE and batch deletion is bounded.

    `report_missing_providers` and `completions.cleanup` each open a write transaction (`BEGIN IMMEDIATE` on SQLite) on every call. Cleanup also runs an unbounded `DELETE FROM batches WHERE NOT EXISTS(...)` over the whole batch table. A frequently scheduled worker therefore holds the SQLite write lock and scans every batch on each tick. Bound the batch delete, and skip the missing-provider update when no unregistered providers exist.

14. **`src/notify_kit/services/worker.py:74`: each job uses three transactions.**

    **Resolution:** Fixed. Fenced finish returns the DeliveryStatus from its transaction, or None for a stale claim. Removed the worker's follow-up status read. Claim and finish remain separate transactions around external operations.

    `claim`, `finish`, and then another `deliveries.get(job.id)` read. `finish` already holds the row and could return the `DeliveryStatus`, which saves one round trip per job.

15. **`src/notify_kit/storage/completion_store.py:169-172`: N+1 query in cleanup.**

    **Resolution:** Fixed. Cleanup selects both DeliveryRecord and CompletionRecord from its join and uses those loaded entities. Removed per-row completion lookups and redundant status rechecks.

    The loop re-selects the `CompletionRecord` for each row, although the query already joined it and filtered on its status. The `status not in (...)` re-check is also redundant. Select both entities in the joined query.

16. **`src/notify_kit/services/worker.py:169-172`: the `job.provider not in self.providers` check never applies.**

    **Resolution:** Fixed. Removed the missing-provider special case. Expiry is handled before provider lookup; every remaining nonexpired claim necessarily has a registered provider.

    A job with an unregistered provider is only claimable once it has expired. `_attempt` then returns without calling the provider, and the `expired` branch already makes it terminal. Remove the special case.

17. **`src/notify_kit/notifier.py:274-296`: duplicated except branches.**

    **Resolution:** Fixed. Combined ProviderError and NotifierError in one except tuple for failed PreparedDelivery snapshots. Recipient isolation and safe diagnostic details are preserved.

    The `ProviderError` and `NotifierError` branches build the same `PreparedDelivery`. Use `except (ProviderError, NotifierError) as error:`.

18. **`src/notify_kit/storage/delivery_store.py:56,204` and `storage/job_store.py:76`: the same `Recipient` is built from a row in three places.**

    **Resolution:** Fixed. Pure delivery_recipient/delivery_status conversions in db/delivery_mapping.py centralize row mapping for receipts, status reads and claims. Transactions remain within storage.

    The `Recipient(username=row.username, name=row.display_name, email=row.email, phone=row.phone)` mapping appears three times. Add one `DeliveryRecord` to `Recipient` helper. A future field such as `locale` could otherwise be missed in one place.

19. **`src/notify_kit/cli.py:109`: `_recipient(_object(json.dumps(value)))` re-encodes each item.**

    **Resolution:** Fixed. Recipient parsing validates the supplied object and fields directly, removing the JSON encode/decode round trip for each array element.

    The item is serialized and parsed again only to check that it is a dict. Check `isinstance(value, dict)` directly.

## Conventions

20. **The tests use private attributes, against `docs/AGENTS.md`.**

    **Resolution:** Fixed. No tests reach through notifier._storage or mutate notifier._worker. Retry policy is constructor-supplied. Low-level lease/gate simulations use an explicit storage fixture's public methods, with outcomes checked through Notifier. These are storage contract tests; no unsafe Notifier API was added for tests.

    `docs/AGENTS.md` says: "Test this package through its public Python API". These tests break that rule:
    - `tests/test_recovery_and_bounds.py:33,35,38,45` (`notifier._storage.deliveries.claim/finish`)
    - `tests/test_recovery_and_bounds.py:179` (`notifier._storage.links.begin`)
    - `tests/test_worker_lifecycle.py:36` (`notifier._worker.retry = ...`)
    - `tests/test_worker_lifecycle.py:61` (`notifier._storage.deliveries.claim`)

    For the retry policy, pass `retry_policy=` to `Notifier`.

21. **Test names break the naming rule in `docs/conventions/tdd_rules.md` §8.**

    **Resolution:** Fixed. All maintained SQLite, example and PostgreSQL tests use test_should_<expected>_when_<condition> with explicit behavior and conditions. Bodies/markers remain except where separately corrected.

    The rule says: "`test_should_<expected>_when_<condition>`". Most new tests have no `_when_` clause, for example `test_should_retry_only_transient_failures_until_attempt_limit`, `test_should_preview_without_persisting_or_sending` and `test_should_fence_an_old_worker_after_lease_recovery`.

## Tests

22. **`tests/test_templates.py:152`: the template-in-use test is marked with the wrong requirement.**

    **Resolution:** Fixed. The pending-snapshot template mutation guard is marked R17. R32 retains dedicated batch-isolation evidence, including malformed output and recipient validation.

    `test_should_prevent_template_mutation_while_snapshot_is_pending` is marked `R32`, but it tests the template-in-use guard (R17/R22), not batch failure isolation. The requirement coverage guard (`test_requirement_coverage.py`) therefore over-reports R32 evidence.

23. **`tests/test_contract.py:40`: the R3 test cannot fail.**

    **Resolution:** Strengthened. R3 constructs a new notifier under explicit socket and remote-provider tripwires, verifies configuration validation runs once, asserts no remote boundary is called, and initializes migrated SQLite. Global socket blocking remains enabled.

    `test_should_construct_and_validate_without_external_network` calls `validate_configuration()` on a no-op double and asserts two empty lists. Its `monkeypatch` argument is unused. Nothing in it would fail if construction did network I/O, beyond what `--disable-socket` already enforces globally. This goes against the tdd_rules "Manual Break" rule.

24. **`tests/test_recovery_and_bounds.py:56`: the timeout test does not cover time-budget cancellation.**

    **Resolution:** Addressed by removing time-budget cancellation and adding a deliberately delayed claim plus successive sends near their individual timeout windows. Each gets its full operation timeout. The genuine slow-provider test still checks uncertain timeout handling.

    `test_should_bound_slow_provider_and_preserve_uncertain_outcome` only covers a provider that is genuinely slow. No test covers a send cancelled because the worker budget ran out before or at the start of the call (finding 1).

25. **Missing regression tests.** No tests cover:

    **Resolution:** Added regressions for exhausted callback continuation; accepted lookup returning unknown or raising; migrated accepted rows and recipient_count; empty-request replay/retention; independent provider recovery keys; concurrent metadata refresh; and identical-metadata link replacement. Storage tests also cover bounded deletion and idle maintenance writes.

    - a completion event that runs out of attempts and is followed by another due event (finding 2)
    - an ACCEPTED job whose status lookup returns UNKNOWN (finding 3)
    - upgrading a database that contains `accepted` rows (finding 4); the migration test only backfills a `delivered` row and never checks `recipient_count`
    - replaying an empty request after cleanup has run (finding 8)
    - a per-provider operation key that stays the same when another provider unregisters (finding 6)

26. **`tests/test_migrations.py:140-172`: the downgrade test reuses a closed notifier.**

    **Resolution:** Fixed. The round-trip test opens and initializes a fresh Notifier after migration and closes that instance. It does not query a closed notifier. The original fixture remains fixture-owned and closes once during teardown.

    `test_should_downgrade_and_upgrade_worker_schema_without_dropping_deliveries` calls `notifier.aclose()` and later `notifier.get_status(...)` on the same instance. The kit fixture then closes it a second time. This only works because `AsyncEngine.dispose()` happens to let a disposed engine be reused. Open a fresh `Notifier` after the migration.

## Fix validation

- 124 offline tests passed with external sockets disabled and warnings treated as errors.
- Runtime line coverage: 95.21% (90% minimum); all 46 requirements have collected dedicated evidence.
- Two PostgreSQL 16 integration tests passed on a private disposable cluster; it was stopped and removed.
- Strict type checking, Ruff lint/format, file-size/class organization checks and test-name checks passed.
- Wheel/sdist build, strict Twine checks and isolated offline installed-wheel migration/SQLite smoke passed.
- Regression tests reproduced the reviewed failures before fixes. The strengthened R3 assertion was deliberately broken, observed failing, restored and passed.
- Local documentation links resolve; all 26 original findings are preserved with individual remarks.

These changes remain part of issue #1 and PR #2. The application must run
alembic upgrade heads before startup for the new nk_0003 schema. No live messages
were sent and no application database was migrated or deleted.

## Re-review remarks (2026-11-02)

Every resolution above was checked against the working tree just before commit
3698652. All 26 match the code. At that point `uv run pytest` passed 123 tests;
the commit reports 124. `uv run ruff check .` is clean. R1 and R2 still apply to
3698652. Like the original review, the remarks below come from reading the code;
no scenario was reproduced.

### Remaining issues

R1. **Finding 13 is only partly resolved: an idle worker still opens a write transaction on every run.**

**Resolution:** Fixed. JobStore.claim now performs a read-only due-work check before opening its write transaction. A positive check still reselects and locks the row atomically (SQLite BEGIN IMMEDIATE / PostgreSQL SKIP LOCKED), so the precheck never grants ownership. The new regression observes all SQL from a public Notifier.run_once() and rejects any idle write/BEGIN IMMEDIATE, not just maintenance writes. This adds a read transaction for each claim in exchange for avoiding idle write locks.

   `JobStore.claim` (`src/notify_kit/storage/job_store.py`) still runs inside
   `session(write=True)`. On SQLite that is `BEGIN IMMEDIATE`, even when nothing
   is due. `report_missing_providers` and `cleanup` now check first with a
   read-only query, and the idle-maintenance test in
   `tests/test_storage_efficiency.py` covers only those two. The delivery claim
   has no such check. With `run_forever` at the default 1-second poll interval,
   an idle example server takes the SQLite write lock once a second.
   The resolution says "an idle worker still performs database reads", which
   understates this. Fix: add the same read-only "anything due?" check that
   `CompletionStore.claim` now does, and extend the idle test to cover
   `run_once` as a whole.

R2. **Shutdown can be delayed by minutes (introduced by the finding 1 fix).**

**Resolution:** Fixed. run_forever passes its stop event into worker batch processing. Delivery and callback loops check it before each new claim; the active operation finishes and commits its result, then remaining work stays durable. Cleanup is skipped when stopping. Tests set stop while a send and, separately, a completion handler are blocked, then verify only the active operation finishes and the next item remains queued/pending. Shutdown is no longer tied to the full batch; provider cancellation cooperation and database responsiveness remain necessary.

   `Notifier.run_forever` checks `stop` only between `run_once` calls. One
   `run_once` can claim up to `max_jobs` (default 100) jobs, each allowed
   `operation_timeout_seconds` (default 30). It can then dispatch up to 100
   callbacks under the same timeout. The FastAPI lifespan in
   `examples/fastapi_server/app/main.py` awaits the task on shutdown, so a slow
   provider can hold shutdown for a long time. Fix: pass `stop` (or a should-stop
   check) into `run_once` and `_dispatch`, check it before each new claim, and
   add a test that sets `stop` while a slow send is running.

### Minor

R3. **A worker crash in the example app goes unnoticed until shutdown.**

**Resolution:** Fixed with immediate error logging, without adding an automatic restart policy. The example registers a task done-callback that retrieves/logs unexpected failures as soon as the worker exits. Cancellation is ignored and normal shutdown is silent. The failure still propagates when lifespan awaits the task on shutdown. The regression asserts the error is logged before leaving lifespan; removing the monitor callback makes it fail.

   If `run_forever` raises, for example on `STORAGE_ERROR`, the task ends and
   the server keeps serving requests with no worker. The exception only shows
   up when the lifespan awaits the task on shutdown. Consider logging it from a
   done-callback, or restarting the worker after a backoff.

R4. **An accepted row can carry a misleading error code and reason.**

**Resolution:** Fixed using the agreed diagnostic distinction instead of discarding lookup errors. A previously accepted delivery remains ACCEPTED, keeps its message ID, and reports DELIVERY_CONFIRMATION_UNAVAILABLE for an inconclusive lookup. Its reason explicitly starts with known acceptance and identifies the lookup problem while retaining safe provider details. Successful later confirmation replaces the transient diagnostic. Existing normal-unknown and raised-lookup regressions now assert the error category and acceptance wording.

   When a status check raises or times out, `_attempt` returns UNKNOWN with
   `error_code=DELIVERY_UNKNOWN` and a reason such as "timed out; outcome
   uncertain". `_transition` correctly keeps the state ACCEPTED, but
   `JobStore.finish` still stores that error code and reason. The status then
   reads `accepted` alongside `DELIVERY_UNKNOWN`. Consider keeping the previous
   error code and reason when reconciliation is inconclusive.

R5. **`uv run ruff format --check .` fails on code examples in three docs files**

**Resolution:** Fixed. Ruff formatted all three Markdown code examples, and just lint / just format now include docs/. A full-checkout ruff format --check . also passes. Earlier validation used the explicit Python-source paths shown in justfile; it did not cover Markdown code fences.

   (`docs/README.md`, `docs/usage.md` and `docs/examples/fastapi_server/providers.md`).
   The same failures existed at 203113b and remain in 3698652, so these changes
   did not cause them. "Fix validation" says Ruff format passed, so that check
   presumably did not cover Markdown; fix these or narrow the documented command.

### Minor drift note

- nk_0003 adds `notify_kit_template_provider.generation` with
  `server_default="legacy"`, but the ORM model declares no server default.
  This is harmless because every insert sets a generation, but it is drift
  between the model and the migration if schemas are ever compared.

**Drift resolution:** Fixed the ORM declarations to match the existing migration
defaults, including generation="legacy" and the other five retained backfill
defaults. No released migration is edited and the schema head remains nk_0003.
Schema parity checks now enable compare_server_default=True on both SQLite and
PostgreSQL; they detect default drift instead of ignoring it.

**Test-count clarification:** Commit 3698652 collected and passed 124 tests after
the automatic FastAPI lifespan test was added. The earlier 123-test run preceded
that final test. The validation record reflects the final run.

### Re-review fix validation

- 128 offline tests passed; 95.39% runtime line coverage (90% minimum).
- Two PostgreSQL 16 tests passed, including server-default schema parity, in a private temporary cluster that was stopped and removed.
- Strict package type checking, full-checkout Ruff lint and full-checkout formatting (including Markdown code fences) passed.
- Wheel/sdist build, strict Twine validation and isolated offline installed-wheel migration/SQLite smoke passed.
- New regressions reproduced idle locking, batch shutdown, diagnostic and default-drift failures before fixes. Removing the worker-monitor callback made its strengthened test fail; restoring it passed.
- All existing review text is preserved, with resolutions added for R1–R5 and the drift note. No application database was changed and no live messages were sent.

These fixes continue on the existing issue #1 branch and PR #2.
