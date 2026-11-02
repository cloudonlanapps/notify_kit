# Changelog

## 0.1.0 — Unreleased

- Add provider-based notification submission, template lifecycle, SQLite/PostgreSQL
  persistence, configurable retries/status checks, fenced recovery, completion
  callbacks, acknowledgement/retention, preview and application-integrated Alembic
  migrations, with an offline-tested FastAPI example and CLI (#1).
- Add a continuous worker with graceful shutdown and full per-operation timeouts;
  resolve PR #2 review findings for acceptance preservation, callbacks, template
  generations, empty-batch retention, preview, validation and storage efficiency.
