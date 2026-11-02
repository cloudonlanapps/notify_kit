# Test-Driven Development (TDD) Rules (Python / notify_kit)

Apply these rules to all changes in this repository. Offline tests live under
`tests/` and run with `just test`; PostgreSQL integration tests live under
`tests_postgres/` (see `docs/testing.md`).

## 1. Red-First Development
- Write a failing test before implementing a feature or fixing a bug.
- A new public method may start as a stub that raises `NotImplementedError` until
  its test is logically sound and the implementation begins.

## 2. Requirement-Driven Coverage
- Every rule in `docs/requirements.md` has at least one dedicated `test_*`
  function marked `@pytest.mark.requirement("Rn")`.
- `tests/test_requirement_coverage.py` fails when a completed rule has no marked
  test or a marker names an unknown rule. Add or move the marker when a rule changes.
- Do not group several requirements into one test; granular tests make contract
  violations obvious.

## 3. Test Through the Public API
- Drive behaviour through the public Python API: `Notifier`, its template and
  lifecycle methods, the worker entry points and the CLI.
- Do not reach into private attributes such as `notifier._storage` or
  `notifier._worker`. Pass policies through constructor arguments.
- Storage contract tests may call storage classes directly when they simulate a
  lease, gate or crash that the public API cannot reach; check the outcome
  through `Notifier`.
- The example application's tests drive its HTTP routes and schemas.

## 4. Logical Verification & Strengthening
- Assert outcomes a caller can observe (for example "the delivery is
  `delivered` and the provider received one send"), not just that a call returned.
- **Assertion-First Rule** — never write a test step without an immediate,
  meaningful `assert`.
- **Query Verification** — after every status or batch query, assert on the result.
- **Modification Cycle** — after every mutation (send, template change, worker
  run, acknowledgement), query the new state and assert on it.
- **Avoid Weak Assertions** — prefer specific state checks
  (`status == DeliveryState.ACCEPTED`) over `is not None` or truthiness.

## 5. Model & Schema Integrity
- Value objects, policies and ORM models are tested for:
    - validation success and failure cases;
    - default values and required fields;
    - schema parity between the Alembic revisions and the ORM metadata, including
      server defaults, on SQLite and PostgreSQL;
    - data preservation across upgrade and downgrade for each migration.

## 6. Failure and Constraint Validation
- Every rule (idempotency, retry limits, template-in-use guards, retention,
  timeouts) is tested on both the success path and the failure path, expecting
  the documented `ErrorCode`.
- Uncertain provider outcomes must be tested to show they never authorize a
  second send.

## 7. Operational Rules for Robust Testing
- **The "Manual Break" Test** — temporarily change an expected value to verify
  the test actually fails. A test that can never fail is not a test.
- **Pass-Rate Caution** — a green suite measures stability, not coverage completeness.
- **No Dead-End Placeholders** — grep for `# TODO` and `pytest.skip` before
  opening a PR. Skipped tests must reference an open issue.
- **Warnings are errors** and runtime coverage has a 90% floor.

---

## 8. Test Naming Convention
- `test_should_<expected>_when_<condition>` — for example
  `test_should_preserve_acceptance_when_status_lookup_is_inconclusive`.

---

## 9. Test Isolation
- **No network dependency** — the default suite blocks external sockets. Use the
  fake providers in `tests/helpers/` (for example `RecordingProvider`) or httpx's
  `MockTransport`. Never send real messages.
- **Per-test database** — the `migrated_path`, `storage` and `kit` fixtures in
  `tests/conftest.py` give each test a fresh, migrated SQLite database. Never
  share state between tests.
- **Disposable PostgreSQL only** — `tests_postgres/` creates and drops its own
  `notify_test_*` databases. Never point it at a production cluster.
