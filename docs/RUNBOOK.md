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
The tests in `tests/e2e/test_db_session.py` and `tests/e2e/test_db_mixins.py` run against a real Postgres (rule P8) and need
`TEST_DATABASE_URL`. Copy `.env.test.example` to `.env.test` (gitignored) and point it at a scratch database, or export the
variable, which wins over the file. Without it those tests fail with a message naming the variable; they are never skipped.
They create and drop their own tables (`poc_session_rollback_probe`, `PocMixinProbe`), so never point them at a database whose
tables you care about. Task 3.1 replaces this with a testcontainers PostGIS database and makes the variable optional.
Postgres time zone does not matter: the app's engine sets the session to UTC.

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
- The tests in `tests/e2e/test_db_migrations.py` create a database named `poc_migrations_<hex>` on the server of `TEST_DATABASE_URL` for each
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
| `uv sync` reports no interpreter satisfies `>=3.14` | no 3.14 installed and downloads are blocked | allow `uv python install 3.14`, or install 3.14 another way; do not lower the pin (rule T2) |

## Release
No release process exists: no CI/CD, staging or production. `.github/workflows/agent-checks.yml` only checks PR
evidence and silent check bypasses; it deploys nothing.
