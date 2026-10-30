# POC-2.1 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving confirms the assumed answers in spec.md (edit them first to change one), including the two new runtime
     dependencies `sqlalchemy[asyncio]` and `asyncpg` (rule C2, Q1), the ask-first edit to `pyproject.toml`, and that
     the smoke test fails rather than skips without `TEST_DATABASE_URL` (Q6), and the mixin choice in Q2 (option b, ADR-0014). Format:
     Approved-by: <name> · <date> -->
Approved-by: volodymyr · 2026-10-30

Pattern followed: `app/core/sentry.py` + `app/config.py` + `app/main.py` from POC-1.6 (cross-cutting code in one `core/` module
that may read `config` and imports no layer; settings validated once in `Settings`; `create_app(settings)` wires lifespan; tests
build the app with explicit `Settings(...)`). Layer rules: ADR-0011, `.claude/rules/project-structure.md` (rules 3, 4, 6).
No Python precedent exists for SQLAlchemy; its mechanics are library facts, checked with Context7 (rule D4) before use:
`create_async_engine`, `async_sessionmaker(expire_on_commit=...)`, `DeclarativeBase` with `MetaData(naming_convention=...)`,
`mapped_column("createdAt", ...)`, mixins on declarative classes, uuid4 default, asyncpg URL form.

## Contract changes
- boundary: none (no route added).
- data: none; no table exists yet.
- config: `Settings` gains `database_url: str | None = None`, validated to start with `postgresql+asyncpg://`. Additive.
- generated output: `uv.lock` by `uv add` (never by hand, T3).

## Requirements (ordered, one commit each; branch `feat/POC-2.1-async-engine-session-base`, one draft PR)

### R1 — `DATABASE_URL` setting and dependencies (S)
- files: `pyproject.toml` + `uv.lock` (`uv add "sqlalchemy[asyncio]" asyncpg`), `app/config.py` (change: `database_url`), `tests/conftest.py` (change: `isolated_settings_env` also clears `DATABASE_URL`), `tests/unit/test_config.py` (change).
- layer: config.
- design: the URL carries a password, so a validation error must not echo it (D8, P4; `run()` reads settings before logging is configured, so the error goes to stderr as a traceback). Set `hide_input_in_errors=True` in `Settings.model_config` (pydantic's own option, confirmed in the installed source and with Context7 before use); this also stops every other setting from echoing its input. The scheme validator's own `ValueError` text names the field and the expected scheme only, never the value, because `hide_input_in_errors` does not cover text the validator writes itself.
- test: unset -> `None`; blank -> `None` (reuse `_blank_to_none`); `postgresql+asyncpg://...` accepted; `postgresql://user:secret@host/db` and `mysql://...` each raise `ValidationError` naming `database_url`, and `"secret"` is absent from `str(exc)` (AC7).
- executed how: `uv run python -I -c` building `Settings(database_url="postgresql://u:secret@h/db")` and printing the error (must not contain `secret`).
- risk: wheels for Python 3.14. `uv add` is the first step; if it fails, stop and report (T2, F2). The PR body gives size, licence and maintenance notes for both packages (python-tooling 5).

### R2 — Engine, session dependency, lifespan (M)
- files: `app/core/db.py` (new: `create_engine(settings) -> AsyncEngine | None`, `create_session_factory(engine) -> async_sessionmaker[AsyncSession]`, `async def get_session(request: Request) -> AsyncIterator[AsyncSession]`), `app/main.py` (change: lifespan builds the engine and factory when `database_url` is set, stores them on `app.state`, `await engine.dispose()` on shutdown), `tests/e2e/test_db_session.py` (new), `tests/conftest.py` (change: a `database_url` fixture reading `TEST_DATABASE_URL`, failing with a message when unset).
- layer: core, wired in `main.py`. `get_session` takes the framework `Request` only inside `core` (project-structure 6 forbids it for services, not here); services receive the `AsyncSession`.
- design: `async with factory() as session: yield session`, no commit (Q5); `expire_on_commit=False`; `pool_pre_ping=True`. No connection is opened at boot.
- test (real Postgres, rule P8): `SELECT 1` through the dependency on a local `FastAPI` app with a test-only route (AC1); two requests see two different session objects and each is closed afterwards (AC2); rollback: a fixture creates a real table, the test route inserts a row through the session then raises, and a second connection counts the rows, asserting `== 0` (the fixture drops the table); with no URL the app boots and health is 200, and the session route raises a `RuntimeError` whose text names `DATABASE_URL` (asserted on the exception, since `TestClient` re-raises, and the client-facing 500 body does not name it) (AC3); `engine.dispose` is awaited on lifespan exit, checked by running the real `create_app` lifespan with a recording engine at the seam `app.main` looks the name up (AC4).
- fixture scope: only tests that take the `database_url` fixture need `TEST_DATABASE_URL`. The AC3 test, the AC4 test (recording engine, no connection) and every existing e2e test stay green without a database. The PR records that the local Postgres may lack PostGIS (ADR-0006 names a PostGIS image); `SELECT 1` and the rollback table do not need it.
- executed how: start `DATABASE_URL=... uv run poc-base-fast-api`, `curl localhost:3001/api/v1/health` (200), SIGTERM, show the exit status and the shutdown log line. The real `SELECT 1` is the smoke test run against the local Postgres on `localhost:5432` (`TEST_DATABASE_URL=postgresql+asyncpg://postgres@localhost:5432/postgres`); the PR records the output.
- risk: the dependency hides a missing URL until first use (AC3 test covers the message); a leaked session on client disconnect (context manager covers it).

### R3 — `Base`, naming convention, three opt-in mixins, ADR-0014 (M)
- files: `docs/decisions/ADR-0014-opt-in-column-mixins.md` (new, committed first in this requirement), `docs/decisions/ADR-0004-data-layer-sqlalchemy-alembic.md` (change: the `Status:` line only, "accepted; the mixin bullet is superseded by ADR-0014"; the `Supersedes:` field records what ADR-0004 itself replaced and stays untouched; R4 adds one line under Follow-ups, nothing else), `app/core/db.py` (change: `NAMING_CONVENTION`, `Base(DeclarativeBase)` with `metadata = MetaData(naming_convention=...)`, `IdMixin`, `TimestampMixin`, `SoftDeleteMixin`), `tests/unit/test_db_base.py` (new).
- decision (spec Q2, option b, chosen by the human): ADR-0014 supersedes only the ADR-0004 bullet that says "a shared mixin carries only `deleted`". It records three opt-in mixins, each used only by tables whose Prisma model has exactly that column, and what stays per table. Read from `../poc-base/api/prisma/models/*.prisma`:
  - `IdMixin`: `id` is Prisma `String @id @default(uuid(4))` with no `@db.Uuid`, so the database type is `text`, not `uuid` (the scope row says "uuid4 id"; the schema wins, and 2.5 proves it). Python `Mapped[str]`, default `str(uuid.uuid4())` generated client-side, as Prisma does (no database default). Used by `Account`, `AccountRole`, `AccountIdentity`, `AccountProfile`, `File`, `Notification`, `DeletedHistory`, `Migration`. Not used by `AccountOnRole` and `NotificationRecipient` (composite keys).
  - `TimestampMixin`: `createdAt` `timestamp(3)` without time zone, NOT NULL, database default now; `updatedAt` `timestamp(3)` **nullable** in the database (as Prisma emits it), but filled by the application on insert and on every update, because Prisma's `@updatedAt` does both (Context7, Prisma 7 docs: the client fills each `@updatedAt` field when code creates or updates a row; no database default). So a Python-side `default` and `onupdate`, both the current UTC time. Values are UTC. Used by `Account`, `File`, `Notification`. Not used by `Migration` (its `createdAt` is nullable, so 2.3 declares its columns itself) nor by tables with neither column.
  - `SoftDeleteMixin`: `deleted` boolean NOT NULL, Python and server default false. Not used by `Migration` or `DeletedHistory` (no such column).
  - The ADR states the mixins never decide that a table has these columns: 2.2/2.3 pick them per Prisma model, and 2.5 flags any difference.
- layer: core; `models/` import it (ADR-0011).
- design: convention `pk -> %(table_name)s_pkey`, `uq -> %(table_name)s_%(column_0_N_name)s_key`, `ix -> %(table_name)s_%(column_0_N_name)s_idx`, `fk -> %(table_name)s_%(column_0_name)s_fkey`, the shape Prisma emits, so 2.5 diffs less. Column types come from the Prisma read above; `timestamp(3)` is `postgresql.TIMESTAMP(precision=3)`. Exact SQLAlchemy mechanics for mixin columns on a declarative base (`mapped_column` in a mixin, `declared_attr` only if a column must be copied per class, `onupdate`) are checked with Context7 (D4).
- test (no database): a scratch `DeclarativeBase` subclass sharing `NAMING_CONVENTION` (the real `Base.metadata` stays empty for 2.4) with a mixed-case table checks AC5 and AC6: constraint names; `CreateTable` DDL compiled for the postgresql dialect has quoted `"Thing"` and `"createdAt"`, `id` is `TEXT` primary key, `createdAt` is `TIMESTAMP(3) WITHOUT TIME ZONE NOT NULL`, `updatedAt` is `TIMESTAMP(3) WITHOUT TIME ZONE` and nullable, `deleted` is `BOOLEAN NOT NULL` with default false; each mixin works alone; two instances get different ids; `updatedAt` is set on insert and moves forward on update (clock injected or compared with a bound, never a sleep).
- executed how: `uv run python -I -c` that prints the compiled DDL.
- risk: Prisma's actual types differ from the assumption; caught by reading the schema first. Nothing is asserted as parity here (ADR-0004: 2.5 proves it).

### R4 — Env templates, docs, final gate (S)
- files: `.env.example`, `.env.development.example` (comment moves `DATABASE_URL` to "read today", task 2.1), `docs/ARCHITECTURE.md` (Current: `core/db.py`, lifespan engine; "Where data truth lives": still no table; Decided: 2.1 built), `docs/RUNBOOK.md` (`DATABASE_URL`, `TEST_DATABASE_URL`, no-database behaviour, how to run the smoke test), `docs/ARCHITECTURE.md` also lists ADR-0014 under Decided; ADR-0004 gets one line under Follow-ups (the naming convention lives in `core/db.py`), on top of the R3 status-line edit, `docs/features/POC-2.1/spec.md` (ACs ticked).
- test: whole command map once on the final tree (`ruff check`, `ruff format --check`, `mypy`, `pytest tests/unit`, `pytest tests/e2e` with `TEST_DATABASE_URL` set, `uv build`); `git diff --stat main` shows only the listed files.
- executed how: paste the full output into the PR.

## Docs to update in this PR
- [ ] docs/features/POC-2.1/spec.md (ACs ticked) · [ ] docs/ARCHITECTURE.md · [ ] docs/RUNBOOK.md · [ ] ADR-0014 (new) and the ADR-0004 status line
- [ ] docs/DOMAIN_GLOSSARY.md: none (no new domain term; "Delete" already means soft delete)
- not edited here, for the human: the scope-doc row 2.1 status.

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| No 3.14 wheel for `asyncpg` | blocks the whole package | `uv add` is the first step of R1; stop and report |
| The scope row says "uuid4 id" but Prisma's `String` id is `text` | wrong column type, parity diff in 2.5 | already read from `models/*.prisma`; ADR-0014 records `text`; 2.5 confirms against `pg_dump` |
| A wrong-scheme `DATABASE_URL` echoes its password in the boot error | secret on stderr (D8, P4) | R1 test asserts the password is absent from `str(exc)` |
| Smoke test needs Postgres and Docker is down | cannot run B1 evidence | local Postgres on :5432 answered `select 1` during planning; Q6 asks for the policy |
| `pytest tests/e2e` now fails without a database | friction for a fork until 3.1 | RUNBOOK states it; 3.1 removes it with testcontainers |
| A test model on the shared `Base` pollutes metadata Alembic will diff | false diffs in 2.4 | R3 test uses a scratch base, never `Base` |

## Assumptions
- The open questions in spec.md hold as written; `Approved-by:` confirms them and the two dependencies.
- Context7 checks of the SQLAlchemy async APIs are owed at implementation (D4).
- `pyproject.toml` is ask-first; the only change is the `uv add` line. `.claude/settings.json` is not edited. CI is not touched (T4).
- Estimate: R1 S, R2 M, R3 M, R4 S, about the scope doc's 3 h plus the Prisma type check.
- Python is the interpreter `uv` selects from `.python-version` (3.14); system `python3` is never used (T2).
