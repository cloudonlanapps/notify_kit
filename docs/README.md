# notify_kit

A Python >=3.12 notification package with application-owned providers, stored
templates and persistent per-recipient delivery jobs. The application selects
providers and starts a continuous worker or schedules worker invocations. Provider integrations are supplied by the application; the included FastAPI
example demonstrates console, fake SMS, Brevo and Resend adapters.

Start with the [usage guide](usage.md) for the application integration workflow.

## Development

```bash
uv sync
# Optional PostgreSQL driver:
uv sync --extra postgres
just check
```

See [the FastAPI example](examples/fastapi_server/README.md) for the manual HTTP
workflow and [the provider contract](provider_contract.md) for plugin APIs.

## Application-owned Alembic migrations

The application owns **when and where migrations run**. notify_kit ships an
independent `notify_kit` revision branch as Python package resources. The
application's existing Alembic environment loads both its revisions and the kit's
revisions, using one connection and the existing `alembic_version` table.

Notifier startup never applies migrations or calls `create_all()`. Run deployment
migrations first, then start the server and notification workers. The database
must already exist and the migration account must have DDL permissions.

### 1. Include the packaged versions in alembic.ini

Retain your application's existing script_location and revision directory. Add
the package location, with newline separation so the resource colon is preserved:

```ini
[alembic]
script_location = %(here)s/alembic
path_separator = newline
version_locations =
    %(here)s/alembic/versions
    notify_kit:migrations/versions
```

Do not copy package revisions into application versions/, and do not hardcode a
site-packages filesystem path. The package dependency must be installed in the
same uv environment as Alembic. Alembic is included in the kit's dependencies.
Keep packaged historical revisions installed; do not edit them in the application.

### 2. Compose metadata and filters in alembic/env.py

Keep your application's existing model imports, URL configuration, logging and
online/offline connection setup. Import the kit integration helpers:

```python
from notify_kit.migrations.integration import (
    exclude_kit_names,
    exclude_kit_objects,
    migration_metadata,
)

# ApplicationBase is your existing, fully imported application ORM base.
target_metadata = [ApplicationBase.metadata, migration_metadata()]
```

If you already have multiple metadata objects, append migration_metadata() to
that list. Kit and application table keys must be distinct. Kit tables use the
reserved `notify_kit_` prefix.

Pass these options to context.configure() in BOTH online and offline paths:

```python
context.configure(
    connection=connection,  # Offline mode keeps your existing url=... instead.
    target_metadata=target_metadata,
    include_name=exclude_kit_names,
    include_object=exclude_kit_objects,
    compare_type=True,
    render_as_batch=connection.dialect.name == "sqlite",  # Online mode.
)
```

The filters prevent application autogeneration from creating, changing or dropping
kit tables. They do not suppress explicit operations in packaged kit migrations.
If you already have filters, compose them using AND rather than replacing them:

```python
def include_name(name, type_, parent_names):
    return (
        exclude_kit_names(name, type_, parent_names)
        and application_include_name(name, type_, parent_names)
    )


def include_object(object_, name, type_, reflected, compare_to):
    return (
        exclude_kit_objects(object_, name, type_, reflected, compare_to)
        and application_include_object(object_, name, type_, reflected, compare_to)
    )
```

Use your existing application connection and transaction management. Do not
construct another notification engine inside env.py. The example env.py supports
config.attributes["connection"] for application-controlled Python invocation.

### 3. Use all heads in the normal deployment

```bash
uv sync --locked
uv run alembic upgrade heads
# Only after success: start the server and workers.
```

Use `heads`, not `head`: independent application and kit branches have separate
heads. `alembic current` reports the applied branches; `alembic heads` reports
available heads. Do not merge independent application and kit branches merely to
avoid the plural command. Existing application revisions do not need relabelling.

The application can also invoke its standard Alembic configuration from Python:

```python
from alembic import command
from alembic.config import Config

# Synchronous deployment/setup entry point, not per-request code.
command.upgrade(Config("alembic.ini"), "heads")
```

For an async application-owned deployment routine using an existing async engine:

```python
from alembic import command
from alembic.config import Config


def upgrade_on_connection(connection):
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    command.upgrade(config, "heads")


async with application_engine.begin() as connection:
    await connection.run_sync(upgrade_on_connection)
```

Your env.py must honor the injected connection instead of calling asyncio.run():

```python
if context.is_offline_mode():
    run_migrations_offline()
elif config.attributes.get("connection") is not None:
    do_run_migrations(config.attributes["connection"])
else:
    asyncio.run(run_async_migrations())
```

Do not call synchronous command.upgrade directly on a running event loop. Run
migrations once before starting replicas; do not race multiple lifespan upgrades.
The runnable example includes the complete env.py implementation.

### 4. Generate application revisions only in application versions/

For the example, the application branch is labelled `app`:

```bash
uv run alembic revision --autogenerate --head app@head \
    --version-path alembic/versions -m "application change"
```

Use your existing application's branch label or explicit current application head
revision instead of app@head. Specify --version-path so no revisions are written
into the installed notify_kit package. Review autogenerated operations before use.
Kit maintainers ship future kit changes as new immutable revisions linked to the
previous kit head, using batch alteration for SQLite where needed. Each new kit
revision updates notify_kit_schema_state to its own revision; a reversible
downgrade restores the previous marker. SCHEMA_REVISION in the package must match
the packaged head. Historical migrations must not import current ORM definitions.

### 5. Runtime schema compatibility

After deployment migrations, construct the notifier normally:

```python
storage = DatabaseStorage(url=database_url)
notifier = Notifier(storage=storage, providers=providers)
await notifier.initialize()  # Read-only schema compatibility check.
```

The `notify_kit_schema_state` table contains a runtime compatibility marker. It is
not another Alembic version table: Alembic history still uses the application's
shared alembic_version. The marker allows startup to check the kit version without
needing to load the application's revision graph or interpret its head IDs.
Missing tables/columns, absent marker, or a marker different from the installed
package produce SCHEMA_MISMATCH and stop startup. Newer databases are not silently
accepted by older packages. Do not manually alter the marker to bypass checks.

### Existing databases from this pre-migration draft

Earlier code created tables through create_all(), without Alembic history. The
initial migration intentionally does not silently adopt, overwrite or drop them.
It creates the current schema on a fresh database. Running it over existing kit
tables will fail, not certify them as migrated.

For disposable manual-example data, stop the server and explicitly choose a fresh
database (or deliberately delete the old example database after deciding its data
is no longer needed). For data that must be preserved, back up the database and
write/review a one-time conversion/adoption migration for its actual schema. Older
recipient `address` values cannot reliably be inferred as usernames, emails or
phone numbers. Do not run `stamp heads` or insert the compatibility marker without
validating the schema and converting that data. No automatic adoption/conversion
is implemented or performed by this change.

### Package upgrades and rollback

Upgrade the installed package first so its new revisions are available, run the
application's upgrade heads, then start compatible application processes. Back up
retained jobs before schema changes. Destructive upgrades need an application
maintenance window or an explicitly compatible staged rollout. Package rollback
does not automatically downgrade the database. The initial downgrade removes all
kit tables and data; do not run it against data you intend to keep.

This integration assumes application and kit tables use the same database and
schema/search path. A separate notification database needs its own Alembic
connection/environment; do not reuse the application database's version history
for a different database. Custom PostgreSQL schemas are not configured by this
example.

Alembic documents [multiple version lineages](https://alembic.sqlalchemy.org/en/latest/branches.html)
and [metadata/autogeneration filters](https://alembic.sqlalchemy.org/en/latest/autogenerate.html).

See the [validation record](validation.md) for the latest local results.

## Validation and release preparation

```bash
uv sync --locked
just lint
just typecheck
just test
just package
```

The default suite blocks network sockets, uses temporary SQLite databases and
mocked HTTP transports, and requires no provider keys. All documented requirements
have collected test evidence. Runtime coverage has a 90% floor; immutable Alembic
revision files are validated through schema parity, data-preserving upgrades,
downgrade/upgrade round trips and PostgreSQL SQL generation instead of line coverage.

just package builds wheel/sdist, runs strict Twine metadata checks, installs the
wheel offline into an isolated environment using a temporary wheelhouse of the
validated runtime dependencies, then checks packaged migrations and SQLite CRUD.
No publishing occurs. The wheel includes py.typed and every historical migration.

See [testing guide](testing.md) for PostgreSQL integration and negative-test
verification. CI checks Python 3.12/3.13 plus a PostgreSQL 16 service. Real provider
sends are deliberately excluded from CI; verify credentials/sender setup manually
before delivery to a recipient you control. No credentials belong in the repository.
