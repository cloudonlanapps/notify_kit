# Contributing to notify_kit

notify_kit is a standalone Python package. Every code change is tracked through a
GitHub issue and merged through a pull request. The only exception is the process
files listed below.

## The golden rule

> **No code change without an issue. No merge without a PR linked to that issue.**

This applies to library code, tests, the example application, scripts, CI,
packaging and dependency bumps — everything except the process files below.

## Exception for process files

Edits to `CLAUDE.md`, to `docs/CONTRIBUTING.md`, or to other files under `docs/`
do not require an issue. Commit them directly to `main`. If you are on a feature
branch, switch to `main`, commit, push, then cherry-pick into the feature branch.

Pushing to `main` still needs the user's confirmation when an AI agent does it.

---

## Workflow

```
1. Open an issue
   ↓
2. Create a branch from main
   ↓
3. Write failing tests, implement, run the checks locally
   ↓
4. Open a PR linked to the issue ("Fixes #N")
   ↓
5. Review → squash merge to main
```

## Conventions

How code and tests are written lives in [`docs/conventions/`](conventions/):

- [`coding_rules.md`](conventions/coding_rules.md) — file organisation, module
  boundaries, naming, formatting, size limits, `uv` usage.
- [`tdd_rules.md`](conventions/tdd_rules.md) — red-first TDD, requirement
  coverage, assertions, isolation, test naming.

Package requirements are in [`requirements.md`](requirements.md). Unresolved
design choices need agreement before they become implementation requirements.
How to run the checks is in [`testing.md`](testing.md) and
[`validation.md`](validation.md).

---

## 1. Open an issue

Open an issue at <https://github.com/cloudonlanapps/notify_kit/issues>. Describe
the problem or the capability, and the requirement (`Rn` in `docs/requirements.md`)
it concerns when there is one.

Use GitHub's default labels: `bug`, `enhancement`, `documentation`, `question`,
`duplicate`, `invalid`, `wontfix`, `good first issue`, `help wanted`.

## 2. Branch naming

Branches include the issue number and a short slug:

```
<type>/<issue-number>-<short-slug>
```

Examples:

```
bug/12-retry-after-ignored
feature/15-sms-provider
task/18-bump-sqlalchemy
```

An AI agent may use its own prefix in place of `<type>`, keeping the issue number
and slug, for example `codex/1-notifier-provider-foundation`.

Always branch from `main`.

## 3. Commits

- Use a type prefix and the imperative mood: `feat: add delivery status lookup`,
  `fix: keep acceptance after failed lookup`, `test: cover lease expiry`,
  `docs: describe retention policy`.
- Reference the issue in the body when context helps: `Refs #42`.
- Keep commits focused; one logical change per commit.
- Run `just lint` before committing. Code is formatted with `ruff format`
  (configuration in `pyproject.toml`).

## 4. Pull requests

- **Title:** clear, under 70 characters.
- **Body:** includes `Fixes #N` (or `Closes #N` / `Refs #N`) so GitHub links and
  closes the issue. State which tests cover each part of the change.
- **Target branch:** `main`.
- **One issue per PR** when possible. Bundle only tightly related issues.
- `just check` (lint, type check, tests with the 90% coverage floor, packaging)
  must pass locally, and all CI checks must pass before merge.
- At least one human review for non-trivial changes.
- **Changelog:** if the change affects the public API (exported classes and
  functions, provider contract, error codes, schema migrations, CLI, behaviour a
  caller can observe), add a line to the current section of
  [`CHANGELOG.md`](CHANGELOG.md) with the issue number:
  `- Description of change (#N).` Internal refactors and test-only changes do
  not need an entry.
- **Migrations:** a schema change ships as a new Alembic revision in
  `src/notify_kit/migrations/versions/`. Never edit a released revision.

## 5. Versioning

The package version is `version` in `pyproject.toml` and follows semantic
versioning. While the version is `0.x`, a minor bump may contain breaking
changes; record them in the changelog. Releases are tagged `v<version>`.

## 6. Merging

- Merging is a human decision; there is no auto-merge.
- **Default: squash merge.** `gh pr merge <num> --squash`. The squash commit
  title ends with `(#N)`.
- **Use `--rebase` only for a curated series** whose individual commits are worth
  keeping on `main`.
- **Do not use `--merge`.** Merge commits are not used on `main`.
- **Do not delete the feature branch on merge.** Branches stay on the remote so
  the PR's individual commits remain reachable.
- Never push code directly to `main`. Only process-file commits go directly to
  `main` (see [Exception for process files](#exception-for-process-files)).

## 7. Closing issues

- An issue closes automatically when a PR with `Fixes #N` is merged.
- If an issue is invalid or won't be done, close it with a comment explaining
  why, and apply `wontfix` or `invalid` as appropriate.

---

## Working with AI coding agents

Contributors may use AI coding agents such as Claude Code or Codex from their
terminal, with the `gh` CLI for issues and pull requests. A typical session:

```
You: "implement issue #42"
Agent:
  → gh issue view 42
  → creates branch feature/42-...
  → writes failing tests, implements, runs just check
  → commits
  → confirms with you
  → pushes the branch
  → gh pr create --title ... --body "Fixes #42"
```

Rules for agents on this repository:

1. **Always work from an issue.** If asked to make a code change without one,
   propose creating it first. Process-file edits (`CLAUDE.md`, `docs/`) are the
   exception and go directly to `main`.
2. **Always branch from `main`.**
3. **Never push, open a PR, or merge without explicit user confirmation.**
4. **Ask whether to squash or rebase** when the user authorizes a merge.
5. **Always link PRs to their issue** with `Fixes #N` in the PR body.

These rules are also in the root `CLAUDE.md` (symlinked as `AGENTS.md`), which
agents load automatically.
