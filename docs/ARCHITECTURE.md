# Architecture

> What the system **is** and where code belongs. Structure truths only — no style preferences (those live in `.claude/rules/`).
> Update in the same PR as any structural change (rule E1).

**Status: skeleton with decisions recorded.** "Current" exists and was run. "Decided" is settled by ADR-0003 to ADR-0024 but not yet
built. "Planned" is still intent from the scope doc and is decided by the task named beside it.

## Current

### Repo layout
| Path | What lives here | Deployable? | Owner |
|------|-----------------|-------------|-------|
| `app/` | the importable package; `__init__.py` holds only a docstring. `main.py` has `create_app()` (lifespan, which runs the seed items before serving when a database is configured, CORS, the error handlers, the tags, the six routers, `GET /api/v1/health`), and `run()`; `cli.py` has the project commands (`python -m app.cli --export-openapi`, task 4.1, [ADR-0020](decisions/ADR-0020-cli-module.md)); `config.py` has `Settings` (with the four JWT settings, `parse_duration` and the upload limits `file_max_size` and `file_allowed_mime_types`, task 8.1) and `get_settings()`; `dependencies.py` holds `current_account` and `refresh_account` (task 4.4; `create_app` stores the settings in `app.state.settings` for them) and `require_roles(*roles)` (task 5.2: authenticates, loads the caller's roles through `AccountRoleService`, 403 `FORBIDDEN` when none matches, 401 first) | yes, `uv run poc-base-fast-api` | backend |
| `app/routers/`, `app/schemas/`, `app/models/`, `app/services/` | the layers: one file per module (`account`, `account_profile`, `account_role`, `auth`, `files`, `notifier`; in `models/` the last two are `file.py` and `notification.py`) in each; `models/account.py`, `account_profile.py` and `account_role.py` (task 2.2) and `file.py`, `notification.py` and `system.py` (task 2.3, below) are built; in `schemas/` the request models of `auth.py` and `account_profile.py` (task 4.3) are built, `services/account_role.py` (task 5.2: `AccountRoleService`, `RoleNotFoundError`) `services/account.py` (task 5.3: `AccountService`) `services/file_assert.py` (task 8.1: `FileAssertService`, the upload size and type checks and the owner check) and `services/account_profile.py` (task 5.4: `AccountProfileService`) are built, as are `schemas/account.py` and `AccountProfileResponse` in `schemas/account_profile.py`, `routers/account.py` (task 5.3, one route) and `routers/account_profile.py` (task 5.4, one route); the rest of `services/` and `schemas/` is docstring-only. `models/system.py` holds `DeletedHistory` and `SeedHistory` (task 5.1) and has no counterpart in the other layers | — | backend |
| `app/core/` | cross-cutting code, one module per concern. Built: `logging.py` (JSON formatter and the redaction functions), `sentry.py` (`init_sentry`, event and breadcrumb scrubbing), `body_limit.py` (the 413 middleware), `errors.py` (the `AppError` subclasses, `PayloadTooLargeError` for a 413 upload, `error_body`, `ErrorResponse` and `register_error_handlers`, task 4.2), `validation.py` (`StrictModel` and the field types for email, password, phone and UUID, task 4.3), `security.py` (the JWT codec: `issue_token`, `verify_token`, `TokenClaims`, `AuthConfigurationError`; task 4.4), `openapi.py` (`render` and `is_current` for the exported contract; the command is in `cli.py` because `core` imports no layer), `queue.py` (task 6.1: the `QueueClient` protocol, `ArqQueueClient` with a lazy Redis pool, the JSON job serializers and `retry_delay`; here and not in `workers/` so services and dependencies may import it), `db.py` (`create_engine`, `create_session_factory`, the `get_session` dependency, `Base` with the Prisma-shaped naming convention, and the opt-in `IdMixin`, `TimestampMixin` and `SoftDeleteMixin` of ADR-0014). The rest is docstring-only | — | backend |
| `app/worker.py`, `app/workers/` | the arq worker (task 6.1, [ADR-0024](decisions/ADR-0024-worker-entrypoint-module.md)): `worker.py` holds `WorkerSettings` (`max_tries=3`, `keep_result=0`, JSON payloads, JSON logging with redaction), started with `uv run arq app.worker.WorkerSettings`; `workers/ping.py` is a smoke job that only logs; the SMS and email jobs come with task 6.2 | worker: yes, a second process | backend |
| `app/seeds/` | the seed runner (task 5.1): `base.py` (`SeedItem`, `SeedError`), `runner.py` (`run_seeds`, `seed_database`), `registry.py` (`seed_items`: the base list, plus the development list for `local`, `development` and `test`), `items/init_roles.py` (the two roles), and `python -m app.seeds` (`__main__.py`). The development list (task 5.5, `items/init_admin.py`, `items/init_customer.py`) is the sample admin and three sample customers, for `local`, `development` and `test` only | — | backend |
| `tests/` | `unit/` (no Docker, database or network) and `e2e/` (real Postgres, the app over HTTP), flat `test_<subject>.py` files with names unique across both; the conventions are in `.claude/rules/testing-python.md` and the `test-conventions` skill (task 3.3). `conftest.py` and `utils/db.py` (task 3.1, [ADR-0006](decisions/ADR-0006-test-database-testcontainers.md)): a PostGIS container per session (or `TEST_DATABASE_URL`), a template database built with `alembic upgrade head` and the seeds (a second, unseeded template, copied once per test, is the start of the seed tests: fixture `unseeded_database_url`), one copy per test module, and a `db_session` fixture. Task 3.2: `utils/client.py` (`client_for`, `running_client`), `utils/auth.py` (sign-up and sign-in helper), `utils/queue.py` (`FakeQueue`), `utils/clock.py` (`FROZEN_NOW`) and the fixtures `asgi_app`, `client`, `queue` and `frozen_clock`. Task 6.1: `utils/redis.py` and the fixtures `redis_target` (a Redis container per session, or `TEST_REDIS_URL`) and `redis_settings` (database 15 only, flushed around each test) serve the queue tests in `tests/e2e/test_worker_arq.py`, which need Redis but no Postgres. `testcontainers[postgres]`, `types-docker` and `time-machine` are dev dependencies | — | backend |
| `alembic.ini`, `migrations/` | the Alembic setup (task 2.4, [ADR-0017](decisions/ADR-0017-alembic-migrations-directory.md)): `env.py` is async, takes the URL from `Settings` and compares models with the database; `versions/0001_init.py` is the final state of the four Prisma migrations, hand-written and frozen; `0002_seed_history.py` adds `SeedHistory` (task 5.1). Tooling beside `app/`, not part of the wheel | — | backend |
| `pyproject.toml` | project metadata, `requires-python >=3.14`, runtime `dependencies` (fastapi, uvicorn, pydantic-settings, sentry-sdk, sqlalchemy[asyncio], asyncpg, alembic, email-validator, phonenumbers, pyjwt, arq: a deploy runs `alembic upgrade head`), a `dev` group (ruff, mypy, pytest and plugins, httpx, testcontainers, types-docker, time-machine), the tool settings for ruff, mypy (which also checks `migrations/`) and pytest, script `poc-base-fast-api` (`app.main:run`, ADR-0012), build backend `uv_build` with `module-name = "app"` and `module-root = ""` | — | backend |
| `uv.lock`, `.python-version` | lockfile (uv-owned) and the interpreter pin (3.14) | — | generated / backend |
| `.env.example`, `.env.development.example` | env templates with placeholders only; a real `.env` is gitignored | — | backend |
| `docs/`, `.claude/`, `.github/` | agent config, knowledge docs, PR template and the evidence-check workflow | — | backend |

There is a single root-level `app/` package, laid out by layer ([ADR-0011](decisions/ADR-0011-project-structure.md), rule file `.claude/rules/project-structure.md`). No `src/`, `api/` or `web/` directory is part of the repo.

### Where data truth lives
Only the seed runner, `AccountRoleService.add_account_to_role` (task 5.2) and `AccountService.create_customer` / `create_password_account` (task 5.3; no route calls them yet), `AccountProfileService.update` (task 5.4, through `PATCH /accounts/{accountId}/profile`) and the development seed items of task 5.5 (the admin and three customers) write to a database so far, and the schema has a home: revision `0001_init` (task 2.4) builds the tables below, the two enum
types and the `postgis` extension on an empty database, and `alembic check` fails when the models and the revisions drift apart. The account, file, notification and
system models are mapped (tasks 2.2, 2.3 and 5.1) and importing `app.models` registers ten tables on `Base.metadata`: `Account`, `AccountRole`,
`AccountOnRole`, `AccountIdentity`, `AccountProfile`, `File`, `Notification`, `NotificationRecipient`, `DeletedHistory` and `SeedHistory`, plus the
`AccountRoleType` and `FileType` enums. `FileType` is tied to the metadata directly because no column uses it; without that `create_all` and Alembic
would never emit the Postgres type. `File.content` is `bytea` (ADR-0009), plain and not deferred.
`DeletedHistory` has no `deleted` column, as in the Node schema, and nothing writes to it yet. `SeedHistory` (revision `0002_seed_history`, task 5.1: `id`, `name` unique, `successful`, `result`, `createdAt`) is this base's own table, not Node's `Migration`: one row per seed item, updated in place when a failed item is retried, no `deleted` column. The Node `Migration` table is not mapped: Alembic's `alembic_version` records applied revisions ([ADR-0018](decisions/ADR-0018-drop-migration-table.md)). Names, column types, primary keys, foreign-key actions and
indexes follow the Prisma DDL, except that `AccountProfile` has no `SSN` or `is18YearOld` column ([ADR-0015](decisions/ADR-0015-drop-ssn-and-is18yearold.md)); every unique is a unique index (as Prisma emits it) and `Account_createdAt_idx` is `DESC`. Attributes
are snake_case over the quoted column names (`created_at` for `"createdAt"`, `date_of_birth` for the Node column `"dataOfBirth"`),
relationships are snake_case, plural for a collection, not Prisma's PascalCase ([ADR-0016](decisions/ADR-0016-snake-case-relationship-names.md); `Account.identity`, `Account.account_on_roles`, ...). `AccountProfile.avatarId` has its
foreign key to `File` (`AccountProfile.avatar`, `Account.files`, `Account.notification_recipients`). The data layer plumbing is built: with
`DATABASE_URL` set, `create_app` builds one SQLAlchemy async engine (asyncpg, session time zone UTC) and the lifespan disposes it;
`get_session` gives each request its own `AsyncSession`, which never commits by itself. Without `DATABASE_URL` the app boots and
only a route that needs a session fails. With `DATABASE_URL` set, the lifespan runs the seed items (the roles, today) before the app serves, each in its own transaction under an advisory lock; a failing item is rolled back and recorded in `SeedHistory`, and the boot stops with `SeedError` (a decision of POC-5.1: the Node base logged the failure and served on). The same runner is `python -m app.seeds`. The engine hides statement parameters from error text (`hide_parameters`, rules D8 and P4). No cache is wired. The queue is: `create_app` builds an `ArqQueueClient` into `app.state.queue` (its Redis pool opens on the first enqueue, so the app boots with no Redis; an enqueue with Redis down raises after one connection attempt), the lifespan closes it, and `get_queue` in `dependencies.py` hands it to a route or service. Job payloads cross Redis as JSON, never pickle.

### Boundaries and contracts
The REST contract is written down in [docs/api/ENDPOINTS.md](api/ENDPOINTS.md). Three routes exist, `GET /api/v1/health`, `PATCH /api/v1/accounts/{accountId}/profile` (task 5.4: all three layers of rule P7, the ownership check in `AccountProfileService`; the first route that uses `require_roles`) and `GET /api/v1/account` (task 5.3: the caller's account and live profile; a token whose account is missing or soft-deleted is 401, [ADR-0022](decisions/ADR-0022-self-scoped-routes-need-authentication-only.md)); the six feature routers (`app/routers/<module>.py`, each an `APIRouter` with its own tag) are included under `/api/v1`, and all but `account` and `account_profile` are still empty, and `/docs` lists their tags; CORS allows the origins in `CORS_ORIGINS`. Every error uses one body, `{"error": {"code", "message", "details"}}`, built in `app/core/errors.py` and listed in [docs/api/ERRORS.md](api/ERRORS.md); the OpenAPI contract documents it for 422 and 500. A request body over `MAX_REQUEST_BODY_BYTES` gets 413 before routing (the body limit sits inside CORS, so the 413 carries CORS headers). Logs are JSON on stdout with tokens, passwords, DOB and phone numbers redacted; Sentry is off for `local` and without `SENTRY_DSN`. SIGTERM stops the server after `SHUTDOWN_TIMEOUT_SECONDS` at most. The one generated file is the root `openapi.json`, written by `uv run python -m app.cli --export-openapi` and checked by `tests/unit/test_openapi_stale.py`; a test also fails when a route has no response model or a response model holds an ORM class.

### Environments
| Env | URL | Database | Who may touch it |
|-----|-----|----------|------------------|
| local | `http://localhost:3001` (`uv run poc-base-fast-api`) | optional: whatever `DATABASE_URL` points at | anyone |
| staging | not defined | | team |
| production | not defined | | **not the agent** (rule C5) |

## Decided (ADR-0003 to ADR-0024, built by the scope-doc tasks)
Supersession applies to this repo only; the Node repo's ADRs stay in force there.

- REST with FastAPI under `/api/v1`, Pydantic models, error body `{"error": {...}}`, contract exported to a root `openapi.json`
  with a stale-spec test ([ADR-0003](decisions/ADR-0003-rest-api-fastapi-openapi.md)).
- SQLAlchemy 2 async + asyncpg + Alembic on Postgres/PostGIS, Prisma table and column names as a naming target, not diffed (ADR-0019)
  ([ADR-0004](decisions/ADR-0004-data-layer-sqlalchemy-alembic.md)).
- Alembic in `migrations/` with `alembic.ini` at the repo root, the URL from `Settings`, hand-written frozen revisions that import nothing from `app`,
  `alembic check` with type and default comparison on; it extends ADR-0011 with the import rule for `env.py`
  ([ADR-0017](decisions/ADR-0017-alembic-migrations-directory.md)).
- No `Migration` table: Alembic's `alembic_version` records applied revisions; a third difference from the Node schema next to ADR-0015's two columns
  ([ADR-0018](decisions/ADR-0018-drop-migration-table.md)).
- arq worker on Redis, a separate process; retries by `Retry(defer=...)`
  ([ADR-0005](decisions/ADR-0005-job-queue-arq.md)); the entrypoint is `app/worker.py` and the queue seam is `app/core/queue.py`
  ([ADR-0024](decisions/ADR-0024-worker-entrypoint-module.md)).
- Tests on a real PostGIS Postgres through testcontainers, one template database per run; built in task 3.1 and in use, the seeds are part of the
  template since task 5.1 ([ADR-0006](decisions/ADR-0006-test-database-testcontainers.md)).
- ruff, mypy strict, pytest, installed in task 1.4 and in use ([ADR-0007](decisions/ADR-0007-quality-tooling-ruff-mypy-pytest.md)).
- Opt-in column mixins (`id` as `text`, `createdAt`/`updatedAt` as UTC `timestamp(3)`, `deleted`) and Prisma-shaped constraint names, built in
  task 2.1; it supersedes one bullet of ADR-0004 ([ADR-0014](decisions/ADR-0014-opt-in-column-mixins.md)).
- Relationship attributes follow SQLAlchemy convention (snake_case, plural collections), not the Node base's PascalCase
  ([ADR-0016](decisions/ADR-0016-snake-case-relationship-names.md)).
- `AccountProfile` omits the Node columns `SSN` and `is18YearOld`; with the dropped `Migration` table and the added `SeedHistory` table (revision `0002_seed_history`, task 5.1) these are the known differences from the Node schema (ADR-0019)
  ([ADR-0015](decisions/ADR-0015-drop-ssn-and-is18yearold.md)).
- Schema parity with the Node base is a naming convention, not proven by a `pg_dump` diff; task 2.5 is a smoke run of `alembic upgrade head`, `alembic check` and the app
  ([ADR-0019](decisions/ADR-0019-schema-parity-not-diffed.md)).
- Sentry as the error sink, off for `local` and without a DSN, with whole-event redaction ([ADR-0013](decisions/ADR-0013-sentry-error-reporting.md)).
- `app/cli.py` holds the project commands that need the whole app, starting with the `openapi.json` export; `main.py` stays the app only
  ([ADR-0020](decisions/ADR-0020-cli-module.md)).
- A self-scoped route (the record comes from the token) needs authentication only ([ADR-0022](decisions/ADR-0022-self-scoped-routes-need-authentication-only.md)).
- `seeds` may import `schemas`, so seed data goes through the request models ([ADR-0023](decisions/ADR-0023-seeds-may-import-schemas.md)).
- A service is a class over an `AsyncSession`; it flushes and never commits, the caller owns the transaction
  ([ADR-0021](decisions/ADR-0021-service-shape-and-transactions.md)).
- The console script `poc-base-fast-api` runs uvicorn on `PORT` ([ADR-0012](decisions/ADR-0012-console-script-runs-the-server.md)); it supersedes the script line of ADR-0011.
- Refresh tokens stored as sha256, sent in `x-refresh-token`
  ([ADR-0008](decisions/ADR-0008-auth-tokens-refresh-hash-and-transport.md)).
- Files as multipart upload and authenticated download, bytes in Postgres
  ([ADR-0009](decisions/ADR-0009-file-transfer-multipart.md)).
- API only, `APP_ENV` configuration ([ADR-0010](decisions/ADR-0010-repo-layout-and-configuration.md); its package location is superseded by ADR-0011).
- Root `app/` package laid out by layer: routers, schemas, models, services, plus core, workers and seeds, with the import
  direction defined in [ADR-0011](decisions/ADR-0011-project-structure.md).

## Planned (intent from the scope doc, not yet decided)
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
