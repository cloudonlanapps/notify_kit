# notify_kit project instructions

## Read before working

- docs/CONTRIBUTING.md — contribution and Git workflow.
- docs/conventions/coding_rules.md — Python coding standards.
- docs/conventions/tdd_rules.md — test standards.
- docs/requirements.md — package requirements; unresolved design choices require
  agreement rather than silently becoming implementation requirements.

Explicit user instructions take precedence over these repository conventions.
Respect requests for review-only work, no tests, or no commits. Do not commit,
push, open a PR or merge unless the user authorizes that action.

## Exception for process files

Edits to CLAUDE.md, to docs/CONTRIBUTING.md, or to other files under docs/ do
not require an issue. Commit them directly to main. If you are on a feature
branch, switch to main, commit, push, then cherry-pick into the feature branch.
This rule is also recorded in docs/CONTRIBUTING.md. Pushing still needs the
user's confirmation.

## Repository workflow

This repository is cloudonlanapps/notify_kit, a standalone Python package. This
file, CLAUDE.md, is the project entry point.

- Use this repository's issues and remotes.
- Work on an issue-linked feature branch based on main, named
  <type>/<issue>-<slug>. An agent may use its own prefix in place of <type>, for
  example codex/1-notifier-provider-foundation.
- When the user authorizes a merge, ask whether to squash or rebase. Never use
  --merge and never delete the remote feature branch.
- The package reads no configuration from the environment and has no HTTP API of
  its own; the caller supplies configuration. Do not add environment settings,
  HTTP endpoints or deployment concerns without a notify_kit requirement.
- Test this package through its public Python API, with isolated databases and no
  network dependency. Do not invent test commands or fixtures that do not exist.

## Code organization

- One class per file. Put public data models in models/, one snake_case module
  per class; put storage implementations in storage/ and exceptions in errors/.
- Keep SQL and persistence transactions behind storage methods. Notifier should
  orchestrate providers and storage rather than expose database implementation.
- Use enums or named constants for lifecycle states and policy defaults.
- Document public classes and methods. Keep files at or below 400 lines.
- Export only the intended public API from __init__.py.
- Use uv for Python tooling; format and lint with Ruff before committing.

## Architecture

- Register application-owned provider instances under stable names when creating
  the notifier. The core has no separate channel-routing abstraction.
- The kit supplies SQLite template CRUD using unique template labels.
- Provider linkage consists of template_label, provider and opaque metadata.
  No linkage means skip registration checks and attempt delivery. Existing linkage,
  including empty metadata, means check it and persist refreshed provider metadata.
- Provider plugins interpret templates, prepare payloads and perform delivery.
- Persist one delivery job per recipient; queries must work after restart.
- The caller schedules the worker. The kit owns retry orchestration; uncertain
  outcomes must not silently authorize another delivery attempt.

## Documentation location

Keep every repository document under docs/, including usage, contribution,
validation and example guides. The one exception is this instruction file,
CLAUDE.md, which stays in the repository root. Root AGENTS.md is a discovery
symlink to it; do not create duplicate instruction content elsewhere. Package
README metadata must reference docs/README.md. Keep relative links current when
moving documents.
