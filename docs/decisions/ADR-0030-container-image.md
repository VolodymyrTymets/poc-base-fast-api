# ADR-0030 — One image, two targets; the entrypoint owns wait, migrate and seed

- **Date:** 2026-11-09
- **Status:** accepted
- **Deciders:** Volodymyr
- **Ticket:** POC-11.1
- **Supersedes:** nothing. It fills the "container command" follow-up of ADR-0012 and adds one top-level directory to the layout of ADR-0011.

## Context
Task 11.1 needs an image for the API and one for the worker. The Node base had a wait-for-Postgres loop that announced 30 attempts and made 5
(issue I.6). uvicorn bound `127.0.0.1` only, which is unreachable from outside a container. The slim Python image has no `psql` or `nc`.

## Decision
- One `Dockerfile` at the repo root, `python:3.14-slim` with a pinned uv image, stages `base` (runtime dependencies, the app, a non-root user `app`, `ENTRYPOINT`), `development` (adds the dev group, `tests/` and `openapi.json`; `CMD poc-base-fast-api`) and `worker` (`CMD arq app.worker.WorkerSettings`, `RUN_MIGRATIONS=0`). `.venv/bin` is on `PATH`. No secret is baked in: `.dockerignore` drops `.env*` except the examples, and every setting arrives at run time.
- `docker-entrypoint.sh` requires `DATABASE_URL`, waits for Postgres, runs `alembic upgrade head` and `python -m app.seeds` unless `RUN_MIGRATIONS=0`, then `exec`s the command, so the server is PID 1 and gets SIGTERM. `set -e`: a failed wait, migration or seed stops the container with that status (rule D5).
- Only the API image migrates and seeds. A worker never does, so two containers never race on the schema.
- `scripts/wait_for_postgres.py` makes exactly `DB_WAIT_ATTEMPTS` (30) attempts `DB_WAIT_INTERVAL_SECONDS` (1) apart, through SQLAlchemy (the app's own connector; asyncpg ships no type information), and prints only the exception class, never the URL. `scripts/` is a new top-level tooling directory beside `migrations/`: it imports nothing from `app`, is not in the wheel, and is type-checked. It is not in `app/cli.py` (ADR-0020) because it must run before the schema and the app's settings are usable and needs none of the app.
- New setting `HOST` (default `127.0.0.1`, read by `run()`); the image sets `0.0.0.0`.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| `CMD uvicorn app.main:create_app --factory --host 0.0.0.0` | skips `configure_logging` (RUNBOOK, "Logging"), and writes the port twice |
| a shell `until nc -z` loop | no `nc` in the image, and it cannot tell a refused connection from a missing database |
| a separate migration job in compose | one more service to order; the seeds already take an advisory lock, and one owner is enough |
| a `psql`-based wait | adds a system package to the image for one check |

## Consequences
- Positive: the retry count is the count made, and it is tested (default 30, and the password is never printed).
- Positive: `docker stop` is a graceful shutdown. uvicorn handles SIGTERM itself, so the container exits with status 0 (the 143 in RUNBOOK is a shell's status for a killed process); 137 would mean the grace period ran out.
- Accepted cost: the seeds run twice on a start, in the entrypoint and in the lifespan; the second finds nothing to do, and the entrypoint run is the one with an exit status.
- Accepted cost: the `postgis/postgis` image is amd64 only, so on Apple Silicon the database container is emulated.
- Follow-ups: 11.2 (compose and ports), 11.3 (full-stack check), 11.4 (CI builds the image).

## Revisit when
A production target is defined (this image carries the dev group and the tests in `development` only), or a second schema owner is needed.
