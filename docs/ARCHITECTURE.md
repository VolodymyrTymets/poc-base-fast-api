# Architecture

> What the system **is** and where code belongs. Structure truths only — no style preferences (those live in `.claude/rules/`).
> Update in the same PR as any structural change (rule E1).

**Status: skeleton with decisions recorded.** "Current" exists and was run. "Decided" is settled by ADR-0003 to ADR-0015 but not yet
built. "Planned" is still intent from the scope doc and is decided by the task named beside it.

## Current

### Repo layout
| Path | What lives here | Deployable? | Owner |
|------|-----------------|-------------|-------|
| `app/` | the importable package; `__init__.py` holds only a docstring. `main.py` has `create_app()` (lifespan, CORS, `GET /api/v1/health`) and `run()`; `config.py` has `Settings` and `get_settings()`; `dependencies.py` is docstring-only | yes, `uv run poc-base-fast-api` | backend |
| `app/routers/`, `app/schemas/`, `app/models/`, `app/services/` | the layers: one file per module (`account`, `account_profile`, `account_role`, `auth`, `files`, `notifier`; in `models/` the last two are `file.py` and `notification.py`) in each; `models/account.py`, `account_profile.py` and `account_role.py` are built (task 2.2, below), the rest are docstring-only | — | backend |
| `app/core/` | cross-cutting code, one module per concern. Built: `logging.py` (JSON formatter and the redaction functions), `sentry.py` (`init_sentry`, event and breadcrumb scrubbing), `body_limit.py` (the 413 middleware), `db.py` (`create_engine`, `create_session_factory`, the `get_session` dependency, `Base` with the Prisma-shaped naming convention, and the opt-in `IdMixin`, `TimestampMixin` and `SoftDeleteMixin` of ADR-0014). The rest is docstring-only | — | backend |
| `app/workers/`, `app/seeds/` | the arq worker and jobs, the seed runner; docstring-only | — | backend |
| `tests/` | `unit/` and `e2e/`, a working layout until task 3.3 sets the real one | — | backend |
| `pyproject.toml` | project metadata, `requires-python >=3.14`, runtime `dependencies` (fastapi, uvicorn, pydantic-settings, sentry-sdk, sqlalchemy[asyncio], asyncpg), a `dev` group (ruff, mypy, pytest and plugins, httpx), the tool settings for ruff, mypy and pytest, script `poc-base-fast-api` (`app.main:run`, ADR-0012), build backend `uv_build` with `module-name = "app"` and `module-root = ""` | — | backend |
| `uv.lock`, `.python-version` | lockfile (uv-owned) and the interpreter pin (3.14) | — | generated / backend |
| `.env.example`, `.env.development.example` | env templates with placeholders only; a real `.env` is gitignored | — | backend |
| `docs/`, `.claude/`, `.github/` | agent config, knowledge docs, PR template and the evidence-check workflow | — | backend |

There is a single root-level `app/` package, laid out by layer ([ADR-0011](decisions/ADR-0011-project-structure.md), rule file `.claude/rules/project-structure.md`). No `src/`, `api/` or `web/` directory is part of the repo.

### Where data truth lives
Nothing is persisted yet: no migration exists (Alembic is task 2.4), so no real database holds a table. The account models are
mapped (task 2.2) and importing `app.models` registers five tables on `Base.metadata`: `Account`, `AccountRole`, `AccountOnRole`,
`AccountIdentity` and `AccountProfile`, plus the `AccountRoleType` enum. Names, column types, primary keys, foreign-key actions and
indexes follow the Prisma DDL, except that `AccountProfile` has no `SSN` or `is18YearOld` column ([ADR-0015](decisions/ADR-0015-drop-ssn-and-is18yearold.md)); every unique is a unique index (as Prisma emits it) and `Account_createdAt_idx` is `DESC`. Attributes
are snake_case over the quoted column names (`created_at` for `"createdAt"`, `date_of_birth` for the Node column `"dataOfBirth"`),
relationships are snake_case, plural for a collection, not Prisma's PascalCase ([ADR-0016](decisions/ADR-0016-snake-case-relationship-names.md); `Account.identity`, `Account.account_on_roles`, ...). `AccountProfile.avatarId` is a plain
column until task 2.3 adds `File` and its foreign key. `File` and `Notification*` are not mapped yet (task 2.3). The data layer plumbing is built: with
`DATABASE_URL` set, `create_app` builds one SQLAlchemy async engine (asyncpg, session time zone UTC) and the lifespan disposes it;
`get_session` gives each request its own `AsyncSession`, which never commits by itself. Without `DATABASE_URL` the app boots and
only a route that needs a session fails. No cache or queue is wired.

### Boundaries and contracts
The REST contract is written down in [docs/api/ENDPOINTS.md](api/ENDPOINTS.md). One route exists, `GET /api/v1/health`; CORS allows the origins in `CORS_ORIGINS`. A request body over `MAX_REQUEST_BODY_BYTES` gets 413 before routing (the body limit sits inside CORS, so the 413 carries CORS headers). Logs are JSON on stdout with tokens, passwords, DOB and phone numbers redacted; Sentry is off for `local` and without `SENTRY_DSN`. SIGTERM stops the server after `SHUTDOWN_TIMEOUT_SECONDS` at most. No generated output exists yet.

### Environments
| Env | URL | Database | Who may touch it |
|-----|-----|----------|------------------|
| local | `http://localhost:3001` (`uv run poc-base-fast-api`) | optional: whatever `DATABASE_URL` points at | anyone |
| staging | not defined | | team |
| production | not defined | | **not the agent** (rule C5) |

## Decided (ADR-0003 to ADR-0015, built by the scope-doc tasks)
Supersession applies to this repo only; the Node repo's ADRs stay in force there.

- REST with FastAPI under `/api/v1`, Pydantic models, error body `{"error": {...}}`, contract exported to a root `openapi.json`
  with a stale-spec test ([ADR-0003](decisions/ADR-0003-rest-api-fastapi-openapi.md)).
- SQLAlchemy 2 async + asyncpg + Alembic on Postgres/PostGIS, Prisma table and column names as a target proven by task 2.5
  ([ADR-0004](decisions/ADR-0004-data-layer-sqlalchemy-alembic.md)).
- arq worker on Redis, a separate process; retries by `Retry(defer=...)`
  ([ADR-0005](decisions/ADR-0005-job-queue-arq.md)).
- Tests on a real PostGIS Postgres through testcontainers, one template database per run
  ([ADR-0006](decisions/ADR-0006-test-database-testcontainers.md)).
- ruff, mypy strict, pytest, installed in task 1.4 and in use ([ADR-0007](decisions/ADR-0007-quality-tooling-ruff-mypy-pytest.md)).
- Opt-in column mixins (`id` as `text`, `createdAt`/`updatedAt` as UTC `timestamp(3)`, `deleted`) and Prisma-shaped constraint names, built in
  task 2.1; it supersedes one bullet of ADR-0004 ([ADR-0014](decisions/ADR-0014-opt-in-column-mixins.md)).
- Relationship attributes follow SQLAlchemy convention (snake_case, plural collections), not the Node base's PascalCase
  ([ADR-0016](decisions/ADR-0016-snake-case-relationship-names.md)).
- `AccountProfile` omits the Node columns `SSN` and `is18YearOld`; the parity diff of task 2.5 expects exactly those two differences
  ([ADR-0015](decisions/ADR-0015-drop-ssn-and-is18yearold.md)).
- Sentry as the error sink, off for `local` and without a DSN, with whole-event redaction ([ADR-0013](decisions/ADR-0013-sentry-error-reporting.md)).
- The console script `poc-base-fast-api` runs uvicorn on `PORT` ([ADR-0012](decisions/ADR-0012-console-script-runs-the-server.md)); it supersedes the script line of ADR-0011.
- Refresh tokens stored as sha256, sent in `x-refresh-token`
  ([ADR-0008](decisions/ADR-0008-auth-tokens-refresh-hash-and-transport.md)).
- Files as multipart upload and authenticated download, bytes in Postgres
  ([ADR-0009](decisions/ADR-0009-file-transfer-multipart.md)).
- API only, `APP_ENV` configuration ([ADR-0010](decisions/ADR-0010-repo-layout-and-configuration.md); its package location is superseded by ADR-0011).
- Root `app/` package laid out by layer: routers, schemas, models, services, plus core, workers and seeds, with the import
  direction defined in [ADR-0011](decisions/ADR-0011-project-structure.md).

## Planned (intent from the scope doc, not yet decided)
- Task 2.3 maps `File`, `Notification` and `NotificationRecipient` and, in `account.py` and `account_profile.py`, adds what points at them:
  `AccountProfile_avatarId_fkey` with `AccountProfile.Avatar`, `Account.Files` and `Account.NotificationRecipient`. It extends the table
  set asserted in `tests/unit/test_db_base.py`.
- Redis as a derived read cache (task 9.1 decides it; Redis is also the arq queue backend, so flushing it drops in-flight jobs).
- Reference implementation to port from: the Node `poc-base` repo (NestJS + GraphQL + Prisma), 14 GraphQL operations that
  become REST routes (task 1.2).

## Key flows
None implemented. The flows to port (OTP sign-in, password sign-in and restore, file upload, token refresh) are
described in the Node base's `docs/ARCHITECTURE.md`; the REST versions are specified by tasks 7.1–7.6 and 8.2–8.3 of the scope doc.

## External integrations
| Service | Purpose | Failure mode | Sandbox available? |
|---------|---------|--------------|--------------------|
| Sentry | error reports, off for `local` and without `SENTRY_DSN` ([ADR-0013](decisions/ADR-0013-sentry-error-reporting.md)) | the app runs unchanged; events are dropped if the SDK cannot send | no; point a test DSN at a throwaway project |
| none yet | SMS and email stay log-only (out of scope) | — | — |

## Known constraints and landmines
- The scope doc still says Python 3.12 (task 1.3, `python:3.12-slim`); [ADR-0002](decisions/ADR-0002-python-3-14.md) pins 3.14 and wins. Docker tasks must use the pinned version.
- The first half of the scope doc's row 1.3 (copy `web/`, compose files and ports, work in `api/`) and the ADR-P0x names are stale; [ADR-0010](decisions/ADR-0010-repo-layout-and-configuration.md) drops `web/` and `api/`, and [ADR-0011](decisions/ADR-0011-project-structure.md) puts the package at `app/`. The commands in `CLAUDE.md` assume the repo root.
- `uv.lock` is committed; `.venv/` and `dist/` are not.
