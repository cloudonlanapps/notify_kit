# Validation

Run from the repository root after uv sync --locked:

```bash
just lint
just typecheck
just test
just package
```

just lint also checks Python code fences in docs/. The formatter can be run across
the checkout with uv run ruff format --check .

The default pytest suite blocks external sockets (Unix sockets remain available
for asyncio/SQLite). Each test uses a temporary database initialized through the
application's Alembic environment. No production/example database, API key or
external delivery service is used. MockTransport intercepts all email requests.
Tests exercise Python APIs and the example's HTTP schemas/routers, including
batch isolation, duplicate recipient entries, restart persistence, lease fencing,
status reconciliation, independent callback retries, retention/idempotency expiry,
template registration/update/removal, and migration/data compatibility.

Each documented rule has a dedicated requirement marker. The guard fails if a
completed rule has no collected evidence or a test refers to an unknown rule.
Pytest treats warnings as errors. Runtime coverage has a 90% floor; Alembic
revisions have dedicated schema parity/data preservation/round-trip tests rather
than a line-coverage percentage. CLI entry points and installed artifacts are also
checked by the distribution smoke script.

## PostgreSQL integration

The integration suite is explicit and separate from the no-service default suite.
Supply a disposable PostgreSQL cluster and an account allowed to create/drop test
databases. The suite creates uniquely named notify_test_* databases and removes
them on teardown. Do not point it at a production cluster.

```bash
uv sync --extra postgres
export NOTIFY_KIT_TEST_POSTGRES_URL='postgresql+asyncpg://test_user:test_password@127.0.0.1:5432/postgres'
uv run --extra postgres pytest tests_postgres --allow-hosts=127.0.0.1
```

A private Unix-socket URL works with just test-postgres and requires no TCP socket
exception. CI provisions PostgreSQL 16 and only allows its localhost address.
SQLite and PostgreSQL tests compare migrated schema to ORM metadata. PostgreSQL
also exercises concurrent worker claims and concurrent idempotency submissions.

## Negative verification

Feature tests are written before implementation changes. During release review,
temporarily change a known successful expectation (for example queued to failed
in the first submission test), run that single test and verify that it fails,
then restore it and rerun the suite. Never commit the deliberate break. Verify
that requirement coverage also fails when completed-rule evidence is absent.

## Packaging

just package builds wheel/sdist and validates their metadata without publishing.
The isolated smoke check installs only the built wheel and its prepared production
dependencies with --offline --no-index. It does not import the editable checkout.
It checks py.typed, packaged migration discovery/upgrades and SQLite template CRUD.
The temporary wheelhouse is prepared from the installed, validated runtime
distributions; registry cache metadata is not needed for this offline check.
