# POC-3.1 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving also approves Q1 of spec.md (dev dependency `testcontainers[postgres]`, rule C2).
     Approved-by: <name> · <date> -->
Approved-by: volodymyr · 2026-11-02

Pattern followed: `tests/conftest.py` (`database_url` fixture and `DatabaseEnv`, kept as the server URL provider) and
`tests/e2e/test_db_migrations.py` (`empty_database`: generated name, `CREATE DATABASE` on an AUTOCOMMIT engine, `DROP ... WITH (FORCE)`
in `finally`). Design settled by ADR-0006; no new ADR needed. testcontainers API checked with Context7 (`PostgresContainer(image, driver=None)`).

## Contract changes
- boundary: none (test code only; the app and its routes are untouched).
- data: none. Template and module databases are throwaway.
- generated output: none. `uv.lock` changes through `uv add --dev` only (rule T3).
- test contract: `database_url` keeps its meaning ("a Postgres server I may create databases on"); it now falls back to the container.

## Requirements (ordered; branch `feat/POC-3.1-test-db-fixtures`, one draft PR, one commit each)

### R1 — Dev dependency and container server (M)
- files: `pyproject.toml`, `uv.lock` (via `uv add --dev "testcontainers[postgres]"`); `tests/utils/__init__.py`, `tests/utils/db.py` (new: image constant and `resolve_server_url(env_url, start)`, a plain function that returns the env URL unchanged or calls `start()`, and turns a container-start error into `pytest.fail(..., pytrace=False)` naming both Docker and `TEST_DATABASE_URL`, never a skip), `tests/conftest.py` (change: `database_url` becomes session-scoped and calls `resolve_server_url`; container stopped at session end). Import path: there is no `tests/__init__.py`, so pytest puts `tests/` on `sys.path` and conftest imports `from utils.db import ...`; task 3.3 owns the layout and may move it (noted in the PR body).
- layer: test support.
- test: `tests/unit/test_test_database_resolve.py` (the choice needs no Docker) — env URL set returns it unchanged and `start` is never called; unset calls `start`; a `start` that raises gives a failure whose message names Docker and `TEST_DATABASE_URL`. `tests/e2e/test_test_database.py` — the only test through the fixture: `database_url` is `postgresql+asyncpg://` and `SELECT postgis_version()` answers.
- executed how: `uv run pytest tests/unit/test_test_database_resolve.py tests/e2e/test_test_database.py -v` with Docker up; `docker ps` during and after shows the container created and gone (AC1). Once more with Docker stopped and `TEST_DATABASE_URL` unset: the output with the failure message is pasted (edge case 1).
- risk: testcontainers on Python 3.14, the amd64 image on Apple silicon, and its type hints under `mypy --strict`. First step: `uv add --dev`, a 5-line start/stop run, then `uv run mypy`. If mypy rejects the import, stop and ask a human; no `ignore_missing_imports` or `type: ignore` (B3).

### R2 — Template database built by Alembic (M)
- files: `tests/utils/db.py` (change: `build_template(server_url) -> str` creates `poc_test_template_<hex>`, runs `alembic upgrade head` against it, disposes everything); `tests/conftest.py` (change: session fixture `template_database`, dropped at session end).
- layer: test support.
- test: `tests/e2e/test_test_database.py` — template holds the nine tables of `app.models` plus `alembic_version` at head (AC3).
- executed how: pytest run; `psql` via `docker exec` listing tables of the template while the session runs, pasted.
- risk: `migrations/env.py` is async and reads `DATABASE_URL`: run it from a sync fixture (no running loop) with the variable set through `pytest.MonkeyPatch()` for the call only, `chdir` to a `tmp_path_factory` directory in the same patch (a developer's `.env` stays out), and `get_settings.cache_clear()` before and after, as `empty_database` does. Cheapest check: run R2 alone.

### R3 — Per-module database and `db_session` (M)
- files: `tests/utils/db.py` (change: `create_from_template`, `drop_database`, both only for generated `poc_test_<hex>` names), `tests/conftest.py` (change: module-scoped sync fixture `module_database_url`; function-scoped `db_engine` and `db_session` — a connection with an outer transaction, `join_transaction_mode="create_savepoint"`, rolled back at the end).
- layer: test support.
- test: `tests/e2e/test_test_database_isolation_a.py` and `..._b.py` (AC4, must fail if both shared one database and not depend on order): each module commits one row (its own marker value) through a plain engine on `module_database_url`, outside `db_session`, then asserts the table holds only that row; with a shared database whichever module ran second would see two rows. Separately, in A, a row committed through `db_session` is gone in the next test of the module (AC6). `drop_database` refuses a name outside the `poc_test_` prefix (AC7, unit test, no Docker).
- executed how: `uv run pytest tests/e2e -k test_database -v --durations=10`; the setup durations show per-module time after the first (AC5). Run with the module paths in both orders (A B, then B A).
- risk: AC5 (< 1 s) depends on Docker speed. If missed, report the measurement (B4), do not weaken the criterion.

### R4 — Runbook and spec (S)
- files: `docs/RUNBOOK.md` (change: "Database tests": Docker or `TEST_DATABASE_URL`, container per session, leftover `poc_test_*` cleanup, drop the "Task 3.1 replaces this" sentence), `docs/ARCHITECTURE.md` (change: tests row), `docs/features/POC-3.1/spec.md` (ACs ticked), `.env.test.example` untouched.
- test: none (docs); AC8 gate run in full.
- executed how: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` with Docker up, then again with `TEST_DATABASE_URL` set to a server (AC2), outputs pasted.
- risk: none.

## Docs to update in this PR
- [ ] docs/features/POC-3.1/spec.md (ACs checked)
- [ ] docs/RUNBOOK.md (database tests)
- [ ] docs/ARCHITECTURE.md (tests layout, the testcontainers dev dependency)
- [ ] DOMAIN_GLOSSARY: no new term. ADR: none (ADR-0006 covers it).
- scope doc row 3.1 status is the human's (rule E2: noted in the PR body)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Docker daemon is off here | AC1, AC5 unverifiable | ask the human to start it before R1; else "Not verified" |
| testcontainers or its deps fail on Python 3.14 | R1 blocked | `uv add --dev` then start and stop a container, first step |
| `CREATE DATABASE ... TEMPLATE` fails: template has a session open | R3 | dispose the engine in R2 and assert in a test |
| mypy strict rejects the testcontainers import | R1 blocked, no override allowed | `uv run mypy` right after `uv add --dev` |
| Existing e2e tests break when `database_url` goes session-scoped | AC8 | run `pytest tests/e2e` at the end of R1 |
| Per-module time over 1 s | AC5 | measure at R3 |

## Assumptions
- Spec Q1 to Q4 hold. Image `postgis/postgis:16-3.4` (ADR-0006), asyncpg URL, no xdist. Python is the `uv` interpreter (3.14, T2).
- Estimate: R1 M, R2 M, R3 M, R4 S. Scope-doc estimate is 5 h.
