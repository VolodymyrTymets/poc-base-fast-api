# POC-3.1 — Test DB fixtures

## Problem
Database tests need `TEST_DATABASE_URL` pointing at a hand-run scratch Postgres, and each test file builds its own schema
(`create_all` in a throwaway schema, or an empty database). Nothing builds the schema with the real migrations once and
hands every test module a clean copy. ADR-0006 decided the answer (testcontainers, one template database, a copy per module);
it is not built.

## Goal / business value
Goal 3 (Test base, BUSINESS_MODEL.md) and non-negotiable "tests use a real Postgres". Also unblocks 3.2 and 5.1.

## Scope
- in: a session-scoped `postgis/postgis:16-3.4` container (testcontainers); a session template database built with
  `alembic upgrade head`; a fresh database per test module made with `CREATE DATABASE ... TEMPLATE`; a `db_session` fixture;
  `TEST_DATABASE_URL` to use an existing Postgres instead of Docker; RUNBOOK update.
- **out (explicit):** seeds in the template (task 5.1 adds them; there is no seed runner yet); the HTTP client and auth
  helper (3.2); rewriting the test-conventions skill and rules (3.3); porting the existing database tests onto the new
  fixtures (they keep working through `database_url`); CI (11.4); parallel runs (xdist).

## Acceptance criteria
- [x] AC1 Given Docker is running and `TEST_DATABASE_URL` is unset, when `uv run pytest tests/e2e` runs, then one PostGIS container starts for the session and is removed at the end.
- [x] AC2 Given `TEST_DATABASE_URL` is set, when the suite runs, then no container is started and the template is built on that server.
- [x] AC3 The template database is built by `alembic upgrade head` and holds the nine tables of `app.models`.
- [x] AC4 Given two modules, when module A inserts a row, then module B's database does not contain it.
- [x] AC5 Per-module setup (create from template, drop at the end) takes under 1 s after the first build; the measured time is in the PR.
- [x] AC6 `db_session` gives an `AsyncSession` on the module's database; what a test commits is gone for the next test in the same module.
- [x] AC7 Per-module databases are dropped at teardown; only names the fixture generated are ever dropped.
- [x] AC8 `ruff check`, `ruff format --check`, `mypy`, `pytest tests/unit` and `pytest tests/e2e` pass; no test weakened or skipped.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Docker not running and no `TEST_DATABASE_URL` | the database fixtures fail with a message naming both options; never a skip | rule B3, existing `database_url` behaviour |
| Template still has a connection when copied | Postgres refuses `TEMPLATE`; the build disposes its engine before it yields | Postgres rule |
| Test run killed mid-way | leftover `poc_test_*` databases (env-URL case) or a Ryuk-reaped container; drop by hand, noted in RUNBOOK | as `poc_migrations_*` today |
| Existing tests that use `database_url` | keep working: it now returns the server URL of the container or of `TEST_DATABASE_URL` | scope (C1) |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Add `testcontainers[postgres]` to the `dev` group (pyproject is ask-first, rule C2)? | yes, dev group only, via `uv add --dev`; ADR-0006 already chose it | yes (approval line) |
| Q2 | Docker daemon is not running here; may I ask you to start it for the container run? | yes; otherwise AC1 goes under "Not verified" | yes |
| Q3 | Isolation between tests of one module | `db_session` wraps each test in a transaction rolled back at the end (SAVEPOINT mode, so test commits are undone) | no |
| Q4 | Seeds | not in the template until 5.1; 5.1 adds its call | no |
