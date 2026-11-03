# POC-5.1 — Seed runner

## Problem
A fresh database has no `AccountRole` rows, so nothing that needs a role (sign-up, role guards, the admin and customer seeds of 5.5)
can work. The Node base fills it with `MigrationsService` + `InitRolesMigration` at boot; the Python base has no equivalent.
`0001_init` stays the Node schema, so the bookkeeping table for seeds is a new revision.

## Goal / business value
Goal 1 (scaffolding: a fork boots with its base data) and goal 3 (test base: the test template database already holds the roles).

## Scope
- in: `SeedItem` contract; `SeedHistory` model (`app/models/system.py`) and Alembic revision `0002_seed_history`; the runner; the `init_roles`
  item (ports `InitRolesMigration`: creates `CUSTOMER` and `ADMIN` when `AccountRole` is empty); the item list with a dev-only part for
  `local`/`development`/`test`; run on app startup and via `python -m app.seeds`; seeds applied to the test template database (3.1 hook).
- **out (explicit):** the admin and customer seeds (5.5); a new setting to switch startup seeding off; a seed CLI beyond `python -m app.seeds`
  (no `--only`/`--force`); any endpoint; a `Migration` table (ADR-0018 stays: `SeedHistory` is a different table with a new name).

## Acceptance criteria
- [ ] AC1 Given an empty migrated database, when the runner runs twice, then `AccountRole` holds exactly `CUSTOMER` and `ADMIN` once each and `SeedHistory` one successful `init.roles` row.
- [ ] AC2 Given an item whose `run` raises, when the runner runs, then its writes are rolled back, `SeedHistory` has `successful=false` and `result` with the error text, the runner raises `SeedError`, and later items do not run.
- [ ] AC3 Given a failed row, when the next run succeeds, then the same row (name unique) becomes `successful=true`, `result` cleared.
- [ ] AC4 Given `APP_ENV=production`, when the list is built, then no dev-only item is in it; for `local`, `development`, `test` it is.
- [ ] AC5 `uv run python -m app.seeds` with `DATABASE_URL` set seeds and exits 0; without it exits 1 with a message naming `DATABASE_URL`; a failing item exits 1.
- [ ] AC6 App startup with a database seeds before serving; without `DATABASE_URL` it boots as today.
- [ ] AC7 `alembic upgrade head`, `alembic check` (no diff) and `alembic downgrade 0001_init` work on a PostGIS database.
- [ ] AC8 The test template database already contains the two roles; two modules still do not see each other's rows.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Two processes boot at once | a transaction-level advisory lock serialises items; the unique index on `AccountRole.type` is the backstop | plan |
| `AccountRole` has rows but no history | `needs_to_run` false: item skipped, no history row (as Node) | Node behaviour |
| Failed item on startup | boot stops with the error (not swallowed, D5); Node swallowed it | assumption Q1 |
| Error text stored in `result` | exception class and message only, no SQL parameters or stack | rule D8 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | A seed failure at startup: stop the boot or log and serve? | stop the boot; the row records why; `0002` and 5.5 depend on roles existing | yes, cheap to flip |
| Q2 | `SeedHistory` has no `deleted` column (the row list in the scope doc has none) | none, bookkeeping like `DeletedHistory`; P6 does not apply | no |
