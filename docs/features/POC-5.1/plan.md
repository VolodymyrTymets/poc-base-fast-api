# POC-5.1 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: volodymyr · 2026-11-03 · Q1: a failed seed stops the boot (approved in chat; line recorded by the agent on their instruction)

Pattern followed: Node `api/src/migrations/{migrations.service,migration.service,items/init.roles.migration}.ts` (behaviour to port);
in this repo `app/models/system.py` (`DeletedHistory`: bookkeeping table, no soft delete), `migrations/versions/0001_init.py` (frozen,
hand-written revision), `app/cli.py` + ADR-0020 (command surface), `tests/utils/db.py::build_template` (template hook).
No precedent for a runner; it stays inside ADR-0011 (`seeds` uses `models`, `core`, `config`) and ADR-0017, so no ADR.

## Contract changes
- boundary: none. No route; `openapi.json` unchanged (stale check confirms).
- data: new table `SeedHistory` (`id` text pk, `name` text unique index `SeedHistory_name_key`, `successful` bool default false, `result` text null,
  `createdAt` timestamp(3) default `CURRENT_TIMESTAMP`) via new revision `0002_seed_history`; additive. Rollback `alembic downgrade 0001_init` drops it.
- CLI: new `python -m app.seeds`.
- generated output: none.

## Requirements (ordered; branch `feat/POC-5.1-seed-runner`, one draft PR, one commit each)

### R1 — `SeedHistory` model and revision 0002 (M)
- files: `app/models/system.py` (change: `SeedHistory`), `app/models/__init__.py` (export), `migrations/versions/0002_seed_history.py` (new, frozen, imports nothing from `app`; ask-first path, hook will prompt), `tests/unit/test_db_base.py` (table set + `SeedHistory`), `tests/unit/test_system_models.py` (columns, types, defaults, unique index), `tests/unit/test_initial_revision.py` (head is now `0002_seed_history`; the `0001` checks keep pointing at 0001), `tests/e2e/test_db_migrations.py` (upgrade builds the table, check clean, downgrade to `0001_init` removes only it).
- layer: models, migrations.
- test: as listed; the existing migration e2e suite is the proof that `alembic check` shows no diff.
- executed how: `uv run alembic upgrade head`, `alembic check`, `alembic downgrade 0001_init`, `alembic upgrade head` against a throwaway PostGIS database (`docker run postgis/postgis:16-3.4`, `CREATE DATABASE`); paste output.
- risk: `alembic check` compares unique-index and default; mirror `AccountRole_type_key` style (explicit `Index(..., unique=True)`).

### R2 — Runner and `SeedItem` contract (M)
- files: `app/seeds/base.py` (new: `SeedItem` Protocol `name`, `needs_to_run(session)`, `run(session)`; `SeedError`), `app/seeds/runner.py` (new: `run_seeds(session_factory, items)`), `tests/e2e/test_seed_runner.py` (new; on `unseeded_database_url`, see R3 — add the fixture in this requirement, R3 reuses it).
- behaviour: per item one transaction: `pg_advisory_xact_lock`, skip when a successful row exists or `needs_to_run` is false, else `run` + upsert history row `successful=true` in the same transaction. On error: rollback, then a second transaction upserts `successful=false, result=<ExcType: message>`, log with the item name (no payload), raise `SeedError` from the cause; later items do not run. Soft-delete rule P6 does not apply to `SeedHistory`; the runner issues no `DELETE`.
- layer: seeds (uses models, core).
- test: real Postgres (`db_session`/`db_engine`), fake items: runs once, rerun skips, failure recorded and re-raised and rolled back (AC2), retry flips the row (AC3), concurrent runs (`asyncio.gather` of two runners) leave one history row.
- executed how: covered by the e2e test plus R4 run; paste `pytest` output.
- risk: advisory lock + upsert race; the concurrency test is the cheapest check.

### R3 — `init_roles` item and item list (S)
- files: `app/seeds/items/__init__.py`, `app/seeds/items/init_roles.py` (new: name `init.roles`; `needs_to_run` = no `AccountRole` row; `run` adds one row per `AccountRoleType`), `app/seeds/registry.py` (new: `seed_items(app_env)` = base list + dev-only list, dev-only empty until 5.5, shaped by `APP_ENV` in {local, development, test}), `tests/e2e/test_seed_init_roles.py`, `tests/unit/test_seed_registry.py`.
- layer: seeds.
- unseeded database (named here because R2 and R3 need it): `tests/utils/db.py` gets `build_template(..., seed: bool = True)` and a fixture `unseeded_database_url` in `tests/conftest.py` that builds a second, session-scoped template with `seed=False` and copies it per module (`CREATE DATABASE ... TEMPLATE`, dropped after). The seed tests use it; every other test keeps the seeded one. No test deletes rows to get an empty table (P6). Runner tests commit through the runner's own sessions, so they use an engine on that database (not `db_session`, whose rollback does not apply) and give each test its own item names, because commits persist for the module.
- test: AC1, AC4; roles table non-empty with no history row is skipped.
- executed how: R4 command on a real database; `SELECT type FROM "AccountRole"` output.
- risk: none.

### R4 — Entry points: `python -m app.seeds`, startup, test template (M)
- files: `app/seeds/__main__.py` (new; reads `Settings`, builds engine, `asyncio.run`, exit codes of AC5), `app/main.py` (change: lifespan runs `run_seeds` before the yield when an engine exists), `tests/utils/db.py` (change: `build_template` runs the seeds after `alembic upgrade head` unless `seed=False`), `tests/e2e/test_db_session.py` (change: the `app` fixture points at `module_database_url`, a migrated and seeded database; `test_the_lifespan_disposes_the_engine` patches `app.main.run_seeds` with a `WHY: the test is about engine disposal, seeding has its own tests (POC-5.1)` comment; no assertion is removed or narrowed), `tests/e2e/test_seed_entrypoints.py` (new: module run via subprocess with `DATABASE_URL`, no URL → exit 1; startup seeds an unseeded migrated database; failing seed stops boot).
- layer: seeds, main, tests utils.
- test: AC5, AC6, AC8 (two-module isolation tests already exist and must stay green).
- executed how: `uv run poc-base-fast-api` against a migrated empty database, `curl /api/v1/health`, `SELECT` roles, restart and show nothing added; `uv run python -m app.seeds` twice; paste output.
- risk: tests that start the lifespan on a database without `SeedHistory` (`tests/e2e/test_db_session.py` builds own tables; one test uses an unreachable URL) would now fail at startup. Cheapest check: run `uv run pytest tests/e2e` after this step; fix by giving those tests a migrated database or not running the lifespan, never by skipping seeds in app code.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker), `uv run alembic upgrade head` + `alembic check`, `uv run python -m app.cli --export-openapi --check`. Anything not run goes under "Not verified".

## Docs (same PR, rule E1)
- [ ] docs/features/POC-5.1/spec.md (ACs checked off)
- [ ] docs/ARCHITECTURE.md — `seeds/` built, startup seeding, revision 0002; table count becomes ten; `SeedHistory` listed as an allowed extra table next to ADR-0015 and ADR-0018 (a schema difference from the Node base); ADR-0019 note goes in the PR body
- [ ] docs/DOMAIN_GLOSSARY.md — terms: Seed item, Seed history
- [ ] docs/RUNBOOK.md — `python -m app.seeds`, startup seeding and its failure mode (new: with `DATABASE_URL` set, an unreachable database or a failing seed now stops the boot), template now holds seeds (replaces "seeds join it in task 5.1")
- [ ] docs/decisions: no ADR (no new pattern); fix the "seeds join the template in task 5.1" wording in ADR-0006 notes only if it states a future

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Startup seeding breaks e2e tests that run the lifespan on non-migrated databases | red tests | run `pytest tests/e2e` right after R4 |
| Two replicas seed at once | duplicate or failed boot | concurrency test in R2; unique indexes as backstop |
| Failed seed or unreachable database blocks boot (Q1) | outage on a bad seed; behaviour change from today | the approver answers Q1 in the `Approved-by:` line; flip is one line |

## Estimate
R1 M, R2 M, R3 S, R4 M.

## Not covered
Admin and customer seeds (5.5), a switch to disable startup seeding, Docker entrypoint call (11.1), cache, any endpoint.
