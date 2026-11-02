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

## Applying the imported conventions

docs/CONTRIBUTING.md was copied unchanged from club_server. This repository is
cloudonlanapps/notify_kit, a standalone Python package, not that server.

- Use this repository's issues and remotes. The current implementation concerns
  issue #1. Do not create or modify club_server issues for notify_kit work.
- Work on an issue-linked feature branch based on main. Use the Codex branch
  prefix with an issue number, for example codex/1-notifier-provider-foundation.
- Server deployment settings, coordinated club_* versioning, HTTP endpoints,
  server module snapshots and server release promotion apply only to that server;
  do not introduce them here without a corresponding notify_kit requirement.
- HTTP/role-specific testing rules apply only if such APIs are introduced. Test
  this package through its public Python API, with isolated databases and no
  network dependency. Do not invent test commands or fixtures that do not exist.
- Use notify_kit imports and package paths wherever the imported documents say
  club_server. CLAUDE.md is not required; this file is the project entry point.

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
validation and example guides. Root AGENTS.md is a discovery symlink to this file;
do not create duplicate instruction content outside docs/. Package README metadata
must reference docs/README.md. Keep relative links current when moving documents.
