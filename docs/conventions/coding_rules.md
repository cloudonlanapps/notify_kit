# Coding Standards & Practices (Python / notify_kit)

These rules apply to all Python code in this repository: the `notify_kit` package,
its tests, scripts and the example application. They complement the workflow
rules in `docs/CONTRIBUTING.md` and `CLAUDE.md`.

## File Organization

1. **One class per file** — no modules with many unrelated classes packed
   together. A class's private helper functions may share its file.

2. **Folder names indicate purpose** — files in `storage/` don't need a `_store`
   suffix beyond what names the class, files in `models/` don't need a `_model`
   suffix, and so on.

3. **Correct folder for content type** (under `src/notify_kit/`):
   - `models/` — public value objects, enums and policies, one snake_case module per class
   - `storage/` — database queries and transaction boundaries
   - `db/` and `db/models/` — engine/session setup and SQLAlchemy ORM models
   - `services/` — orchestration helpers such as the worker and template lifecycle
   - `errors/` — exception classes
   - `migrations/versions/` — Alembic revisions
   - `constants.py` — named defaults and limits

   The example application under `examples/fastapi_server/app/` follows the usual
   FastAPI layout: `routers/` for route handlers, `services/` for application
   logic, `schemas/` for Pydantic models and `providers/` for provider plugins.

4. **Meaningful naming** — file and symbol names reflect purpose. `snake_case` for
   filenames and functions, `PascalCase` for classes.

---

## Module Boundaries

5. **`__init__.py` exports only the public API** — export only symbols callers
   are meant to use.

6. **Keep implementation details internal** — don't expose internal helpers to
   work around a problem in another module; refactor instead.

7. **Test data stays in `tests/`** — fixture builders, fake providers and test
   utilities belong under `tests/`, not in `src/notify_kit/`.

8. **No leaky persistence** — SQL and transactions stay behind storage methods.
   `Notifier` orchestrates providers and storage; it does not expose database
   implementation details to callers.

---

## Code Patterns

9. **Use existing models directly** — don't add wrapper classes when an existing
   ORM model or value object already fits.

10. **Avoid naming conflicts** — when a generic name (`Status`, `Item`, `Record`)
    might collide, prefix it with the domain (`DeliveryState`, `CompletionStatus`).

11. **Provider calls stay outside transactions** — never hold a database
    transaction open across a provider's network call.

---

## File Size Limits

12. **Maximum 400 lines per file** — split a file before it grows past the limit.

---

## Code Formatting

13. **Run `ruff format` before every commit** and lint with `ruff check`.
    `just lint` runs both, including Python code blocks in `docs/`.

14. **Zero warnings.** Ruff and `basedpyright --level error` (`just typecheck`)
    must report nothing.

15. **File naming** — `snake_case` for all Python files.

16. **Import order** — stdlib → third-party → project (`notify_kit.*`). Ruff's
    isort rules enforce this.

17. **Documentation** — public classes and methods have docstrings. No
    commented-out code in committed files.

18. **No magic values** — define constants in `constants.py` or as enums (for
    example `DeliveryState`, `ErrorCode`). Inline literals are acceptable in tests.

---

## Git & Workflow

Commit, branch, PR and merge conventions are defined in `docs/CONTRIBUTING.md`
and `CLAUDE.md`. They take precedence over anything below.

19. **Commit message format** — type prefix and imperative mood:
    `feat: add delivery status lookup`, `fix: keep acceptance after failed lookup`,
    `test: cover lease expiry`. The full PR and branch rules are in
    `docs/CONTRIBUTING.md`.

20. **One logical change per commit** — do not mix unrelated changes.

---

## Python Project Management

21. **Use `uv`** — dependency management, virtual environments and script
    execution go through `uv` (`uv add ...`, `uv run pytest`, `just check`).
    Do not use `pip` or `poetry` directly.
