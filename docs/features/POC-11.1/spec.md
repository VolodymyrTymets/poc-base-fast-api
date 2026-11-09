# POC-11.1 — Dockerfile and entrypoint

## Problem
The API and the worker can only be run from a developer's own `uv` install. There is no image, so nobody can start the stack in a container (task 11.2 builds the
compose file on top of this) and the Node base's wait-for-Postgres loop bug (issue I.6: it says 30 attempts and loops 5) has no Python counterpart yet.

## Goal / business value
Goal 1 (scaffolding: a fork starts the API and the worker from one image).

## Scope
- in: `Dockerfile` (`python:3.14-slim` + uv, stages `base`, `development` and `worker`); `docker-entrypoint.sh`; `scripts/wait_for_postgres.py` (the wait with a counted retry);
  `.dockerignore`; a `HOST` setting so the server can listen on `0.0.0.0` in a container (uvicorn's default `127.0.0.1` is unreachable from outside it); RUNBOOK section.
- **out (explicit):** `docker-compose.yml`, `set-ports.sh`, `move-env.sh` (11.2); full-stack check (11.3); CI (11.4); a production target, image publishing, healthchecks in compose;
  `web/`; changing the JSON logging setup.

## Acceptance criteria
- [x] AC1 `docker build --target development .` and `docker build --target worker .` both succeed.
- [x] AC2 `development` starts as a non-root user, waits for Postgres, runs `alembic upgrade head`, `python -m app.seeds`, then `poc-base-fast-api`; `GET /api/v1/health` answers from the host.
- [x] AC3 `worker` runs no migration or seed and waits only for Postgres: it runs `arq app.worker.WorkerSettings` with no migration or seed (the API container owns them), and logs JSON.
- [x] AC4 The wait makes exactly `DB_WAIT_ATTEMPTS` (default 30) connection attempts, `DB_WAIT_INTERVAL_SECONDS` (default 1) apart, then exits 1 naming the count (issue I.6). No password in its output (rule D8).
- [x] AC5 A failing migration or seed stops the container with a non-zero status; nothing is swallowed (rule D5).
- [x] AC6 `SIGTERM` reaches the app (entrypoint ends in `exec`), so `docker stop` is a graceful shutdown (container exit status 0, not killed).
- [x] AC7 `HOST` defaults to `127.0.0.1`; the image sets `0.0.0.0`; `openapi.json` unchanged; no secrets baked into the image.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| `DATABASE_URL` unset | `development`: entrypoint fails fast naming the variable (no point migrating); the API itself still boots without a DB, so `SKIP_DB=1` is not offered | assumption A3 |
| Postgres up but database missing | counted as a failed attempt; last error printed without the URL | assumption |
| `docker run` with another command (`sh`) | entrypoint still waits and migrates, then runs it | assumption |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | Dockerfile location | repo root, not `api/` (ADR-0010/0011) | no |
| A2 | New `HOST` setting is outside the row's file list | needed to be reachable; additive, default unchanged | yes, confirm |
| A3 | Who migrates | only `development` (API); `worker` skips via `RUN_MIGRATIONS=0` so two containers never race | no |
| A4 | Does `development` include dev dependencies | yes (`uv sync --locked`, with the dev group), source copied in, compose may bind-mount it in 11.2 | no |
| A5 | wait implementation | Python + asyncpg (already a dependency); the slim image has no `psql`/`nc` | no |
