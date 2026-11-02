# Database design

notify_kit follows club_server's SQLAlchemy 2.x async design while remaining a
standalone package with explicit caller configuration.

## Configuration

```python
from notify_kit import DatabaseStorage, Notifier, SQLiteStorage

# File-path convenience; uses SQLAlchemy and aiosqlite internally.
storage = SQLiteStorage("notifications.db")

# Alternatively, install notify-kit[postgres] and supply an existing database.
storage = DatabaseStorage(
    url="postgresql+asyncpg://user:password@host:5432/database",
)

notifier = Notifier(storage=storage, providers={...})
await notifier.initialize()
# Use template CRUD, registration, submission, queries and worker invocations.
await notifier.aclose()
```

Credentials/configuration are supplied by the caller, never discovered from the
environment. Database URL objects are also accepted by DatabaseStorage, avoiding
manual URL escaping of passwords. Each storage instance owns its engine and
session factory; the caller closes it after all worker activity stops.

## Structure and transactions

- db/base.py supplies independent DeclarativeBase metadata.
- db/models/ contains one typed ORM class per file using Mapped/mapped_column.
- models/ contains public value objects and internal execution snapshots, not
  ORM entities bound to an active session.
- storage/ owns database queries, transaction boundaries and conversion to value
  objects. Each operation receives a fresh AsyncSession; sessions are not shared
  between concurrent jobs. expire_on_commit=False follows club_server.
- Provider network calls run outside database transactions. Claims are committed
  before sending. Accepted/unknown outcomes are not blindly retried.
- SQLite write operations acquire BEGIN IMMEDIATE before reading state;
  PostgreSQL claims use SELECT FOR UPDATE SKIP LOCKED. Template-link writes lock
  the parent template on PostgreSQL to serialize competing registrations/updates.
- Foreign keys, uniqueness constraints and indexes enforce persistence invariants.
  An explicit delivery position preserves recipient order on both databases.
- JSON columns use SQLAlchemy's portable JSON type rather than PostgreSQL-only
  JSONB. Provider metadata stays opaque; no local/external classification exists.
- Table names use the notify_kit_ prefix so the kit can coexist with application
  tables in an existing database. Application ORM metadata is not imported.

## Schema lifecycle

The package ships immutable Alembic revisions in migrations/versions on a labelled
notify_kit branch. Applications include that directory alongside their own and run
alembic upgrade heads using their normal connection and shared alembic_version.
The root README documents complete integration and autogeneration filtering.

initialize() checks the kit runtime revision marker and required columns without
creating or upgrading tables. Version mismatch stops startup. Packaged revisions
must be upgraded before servers/workers start. Historical raw-SQL/create_all
schemas are not automatically adopted or stamped; data conversion is explicit.

## Other observed club_server conventions

- Services encapsulate business operations; HTTP routers and Pydantic response
  schemas belong to the application. This kit does not acquire a FastAPI dependency.
- Domain exceptions are distinct from HTTP responses. ProviderError remains the
  current safe plugin error; a broader storage exception taxonomy is future work.
- club_server separates ORM entities from public schemas. The kit retains typed
  dataclasses for its Python API; a Pydantic dependency is not required for ORM use.
- club_server uses UTC integer timestamps in many models. The current kit API
  retains its existing Unix-seconds timestamps rather than silently changing units.
- Alembic migrations and async engine disposal are part of the server's lifecycle.
  The kit exposes disposal and packaged migrations; the application owns deployment execution.

The offline test suite uses isolated migrated SQLite databases. Separate PostgreSQL
integration tests create disposable databases and cover schema parity, idempotency
races and competing workers. The worker persists fenced leases, per-recipient
terminal state and an independent completion outbox. Prepared content is cleared
after callbacks stop; configured retention removes status and batch records later.
The initial nk_0001 revision remains immutable; nk_0002 upgrades existing versioned
data to the worker/outbox schema. This unreleased PR corrects nk_0002 so historical
terminal completions are backfilled as handled rather than replayed. Once released,
those revisions remain immutable. nk_0003 adds provider-specific operation identities,
link generation tokens and timestamps/indexing for empty-batch retention. Applications
must run upgrade heads before using this package revision.

Kit-owned link generations guard lifecycle changes without comparing opaque
status metadata. Generation rows survive unregister so recovery keys for another
provider remain unchanged. Empty batches retain their idempotency receipt for the
configured unacknowledged retention period. See docs/testing.md for validation commands.
