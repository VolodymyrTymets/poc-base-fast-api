# Runbook

> How to run this project, and what goes wrong. Written for a human joining on day one — and read by the agent when the environment misbehaves.

## First run
```bash
# prerequisites: uv (>= 0.12), network access for the first interpreter download.
# Python 3.14 is pinned in .python-version; uv fetches it if it is missing.
uv sync                      # creates .venv from uv.lock
cp .env.example .env         # optional: every setting has a default; see the file for the variables
uv run alembic upgrade head  # only with a database: DATABASE_URL set, PostGIS available (see "Migrations")
uv run poc-base-fast-api     # serves the API on PORT (default 3001)
curl localhost:3001/api/v1/health    # {"status":"ok"}
```
`DATABASE_URL` (`postgresql+asyncpg://...`, nothing else is accepted) is optional: unset or blank, the server still boots and
`/api/v1/health` answers, and only a route that needs a database session fails. The tables exist only after the migration
above; there is no cache or queue. `uv build` writes the wheel and sdist
into `dist/` (gitignored). Settings come from the environment first and `.env` second; `.env.development.example` is the
same file for a shared development host. A bad value (for example `PORT=abc`) stops the boot and names the field.

## Logging, errors and shutdown
- Logs are one JSON object per line on stdout, uvicorn's included. `LOG_LEVEL` sets the level. Tokens, passwords, DOB and
  phone numbers are replaced by `[REDACTED]`; this is best effort (rule P4), so still never log a secret.
- Sentry starts only when `APP_ENV` is not `local` and `SENTRY_DSN` is set; with no DSN nothing is sent. See ADR-0013.
- Redaction and the JSON format are set up by `uv run poc-base-fast-api` (`app.main:run`). Starting the app another way, for example
  `uvicorn app.main:create_app --factory`, skips them; a container command (task 11.1) must use the console script.
- A request body over `MAX_REQUEST_BODY_BYTES` (12 MiB by default) is answered 413 with the standard error body.
- `kill -TERM <pid>` (or Ctrl-C) stops accepting connections, lets in-flight requests finish for up to
  `SHUTDOWN_TIMEOUT_SECONDS` (10), runs the lifespan shutdown, then ends with the SIGTERM status (143 in a shell). That is how
  uvicorn behaves, not a crash.

## Database tests
The database tests run against a real Postgres (rule P8, ADR-0006). Where it comes from:
- **Docker (default):** with `TEST_DATABASE_URL` unset, the first database test starts one `postgis/postgis:16-3.4` container
  (testcontainers) and removes it when the session ends. Docker must be running; otherwise those tests fail with a message naming Docker
  and `TEST_DATABASE_URL`. They are never skipped.
- **An existing server:** set `TEST_DATABASE_URL` (`postgresql+asyncpg://...`) in `.env.test` (copy `.env.test.example`, gitignored) or export it;
  the variable wins over the file. No container is started. The role needs `CREATEDB` and, for the `postgis` extension, superuser rights.

On that server the suite builds one template database per session with `alembic upgrade head` (`poc_test_template_<hex>`; seeds join it in
task 5.1) and gives each test module a copy of it (`poc_test_module_<hex>`, made with `CREATE DATABASE ... TEMPLATE`, dropped after the
module). Fixtures in `tests/conftest.py`: `database_url` (the server), `template_database`, `module_database_url`, `db_engine` (the app's
engine on the module's database; commits stay for the module, so use it for checks across connections) and `db_session` (rolled back after
each test, commits included; the default for a test that writes rows).
The fixtures of `tests/conftest.py` only ever drop databases whose name starts with `poc_test_`; `tests/e2e/test_db_migrations.py` drops its own
`poc_migrations_*` databases on the same server. A killed run can leave either kind on an existing server: drop it by hand. A container is
reaped by testcontainers.

The older tests `test_db_account_models.py`, `test_db_file_models.py`, `test_db_mixins.py` and `test_db_session.py` still make their own
schema or tables on the server `database_url` gives, and drop only those. Postgres time zone does not matter: the app's engine sets the
session to UTC.

## HTTP tests
Fixtures in `tests/conftest.py`, helpers in `tests/utils/` (task 3.2):
- `asgi_app`: the real app from `create_app`, on the module's database. A test may add routes to it (`@asgi_app.get(...)`); they live for that test only.
- `client`: an httpx `AsyncClient` on `asgi_app` with the lifespan started before the test and stopped after it (`ASGITransport` does not run
  it by itself). It needs a database (Docker or `TEST_DATABASE_URL`). A test with no database uses `running_client(create_app(Settings()))`
  from `utils.client`; `client_for(app)` is the same client without the lifespan.
- `utils.auth`: `sign_up(client, email, password)` and `sign_in(...)` post to `/api/v1/auth/sign-up` (expects 201) and `/sign-in` (expects 200) and
  return `AuthTokens`; `.headers` is the Bearer header, `.refresh_headers` the `x-refresh-token` one. A wrong status fails the test with the status
  and the start of the body. Until tasks 4.4 and 7.3 exist only stub routes prove it, so its first real run is the 7.3 e2e suite.
- `queue`: a `FakeQueue` that records `enqueue(job_name, *args, **kwargs)` calls (`jobs`, `named(name)`, `clear()`) and never touches Redis. The real
  queue protocol comes with task 6.1, which adapts the fake.
- `frozen_clock`: stops the process clock at `FROZEN_NOW` (2026-01-01 12:00 UTC); `frozen_clock.shift(timedelta(...))` moves it. Use it to
  expire a token or code instead of sleeping. `datetime.now(UTC)` and `utc_now()` (the same instant, naive) follow it; `time.monotonic` does not.
  **It moves this process only:** a database default such as `CURRENT_TIMESTAMP` still reads Postgres's clock, so code under test must pass `utc_now()`.

## Migrations
Alembic (ADR-0004, ADR-0017): `alembic.ini` and `migrations/` at the repo root; revision `0001_init` is the final state of the
Node base's four Prisma migrations. The database URL is read from `DATABASE_URL` (environment first, then `.env`), never from `alembic.ini`.
- `uv run alembic upgrade head` builds the schema on an empty database; `uv run alembic check` fails if the models and the revisions
  differ; `uv run alembic downgrade base` removes the tables and the two enum types and leaves the `postgis` extension (the rows are gone for good).
- `uv run alembic upgrade head --sql` prints the SQL without connecting (it still needs `DATABASE_URL`, to pick the dialect).
- The first revision runs `CREATE EXTENSION IF NOT EXISTS "postgis"`: the server needs the PostGIS files installed and the role must be
  allowed to create the extension (a superuser in practice). The `postgis/postgis` image has both.
- Point `DATABASE_URL` at the database you mean: `.env` is read when the variable is not exported, so check which one a bare
  `alembic upgrade head` will hit before running it.
- A schema change is a new hand-written revision (`uv run alembic revision -m "<what>"`, then fill in `upgrade` and `downgrade`); an applied revision is never edited. Run `alembic check` after a model change: it names what the revision is missing.
- The tests in `tests/e2e/test_db_migrations.py` create a database named `poc_migrations_<hex>` on the test server ("Database tests" above) for each
  test and drop it afterwards, so that role needs `CREATEDB` (and, for the extension, superuser rights). If a run is killed, drop any leftover `poc_migrations_*` database by hand.

## Commands
See the command map in `CLAUDE.md` — that is the canonical list: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e`, `uv run poc-base-fast-api`, `uv run alembic upgrade head` and
`uv run alembic check`. Coverage is a diagnostic, run by hand with `uv run pytest --cov=app`.

## Undocumented steps everyone knows
- The first `uv sync` downloads Python 3.14 if no matching interpreter is installed.
- `uv.lock` is regenerated by `uv`; never edit or delete it by hand (rule T3).

## Common failures
| Symptom | Cause | Fix |
|---------|-------|-----|
| `alembic` prints `FAILED: DATABASE_URL is not set` | no `DATABASE_URL` in the environment or in `.env` of the current directory | export it, or run from the repo root where `.env` lives |
| `extension "postgis" is not available` (or permission denied to create it) | the server has no PostGIS files, or the role is not a superuser | use a PostGIS server (the `postgis/postgis` image) and a role that may create extensions |
| `alembic check` lists tables such as `state` or `geocode_settings` as removed | the database is the default `postgres` database of the `postgis/postgis` image, where the image also installed `postgis_tiger_geocoder` and `postgis_topology` (seen in `pg_extension`) | run against a database made with `CREATE DATABASE`: it starts empty and the first revision adds `postgis` |
| `uv sync` reports no interpreter satisfies `>=3.14` | no 3.14 installed and downloads are blocked | allow `uv python install 3.14`, or install 3.14 another way; do not lower the pin (rule T2) |

## Release
No release process exists: no CI/CD, staging or production. `.github/workflows/agent-checks.yml` only checks PR
evidence and silent check bypasses; it deploys nothing.
