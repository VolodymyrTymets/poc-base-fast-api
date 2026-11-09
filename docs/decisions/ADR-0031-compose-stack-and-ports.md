# ADR-0031 — The compose stack: four services, one env file for containers, one `.env` for ports

- **Date:** 2026-11-09
- **Status:** accepted
- **Deciders:** Volodymyr
- **Ticket:** POC-11.2
- **Supersedes:** nothing. It builds on ADR-0030 (the image) and settles scope decision D9 (env names) for compose.

## Context
Task 11.2 ports the Node base's `docker-compose.yml`, `set-ports.sh` and `move-env.sh`. The Node stack had six services; two were the `web/` apps, which this repo does not have (ADR-0010).
`.env.development.example` already pointed `DATABASE_URL` at host `db` and `REDIS_HOST` at `redis`.

## Decision
- `docker-compose.yml` at the repo root, four services: `db` (`postgis/postgis:16-3.4`), `redis` (`redis:7-alpine`), `api` (target `development`) and `worker` (target `worker`), one bridge network, named volumes `pgdata` and `redisdata`.
  `db` and `redis` have healthchecks and `api` and `worker` wait for both to be `service_healthy`. The API has no compose healthcheck (the slim image has no `curl`; the entrypoint already waits for Postgres) and no bind mount: a code change is `docker compose up -d --build`.
- The containers read `.env.development` (a copy of `.env.development.example`, gitignored). The `db` container takes `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` from the same file; `Settings` ignores them (`extra="ignore"`). The password appears twice (there and in `DATABASE_URL`) and must match.
- The root `.env` is read by compose only to fill `${EXPOSE_API_PORT}`, `${EXPOSE_POSTGRES_PORT}` and `${EXPOSE_REDIS_PORT}` (defaults 3001, 5432, 6379), and by a local non-docker run as the app's settings. It is not passed into any container. The Node base used `api/.env` for the second role; there is no `api/` here.
- `set-ports.sh <BASE>` (1024-65530) gives API = BASE, Postgres = BASE+1, Redis = BASE+2 and writes the three `EXPOSE_*`, plus `PORT`, `REDIS_PORT` and the port of an existing `DATABASE_URL`, into `.env`. Container-internal ports never change.
  Because `PORT` in `.env` is the published API port, a local `uv run poc-base-fast-api` and the `api` container cannot run in the same checkout at once.
- `move-env.sh [--force] <dir>` copies `.env`, `.env.development` and `.env.test` (those that exist) to another checkout, and refuses to overwrite a file already there unless `--force` is given: it may hold that checkout's secrets.
- Both scripts sit at the repo root, not in `scripts/` (ADR-0030): the acceptance criterion and decision D9 call `./set-ports.sh`, and they are for people, where `scripts/` holds what the image runs.
- A second stack is a second checkout or worktree (compose names the project after the directory), given its env files by `move-env.sh` and its ports by `set-ports.sh`.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Keep `web-app` and `web-admin` services | no `web/` in this repo (ADR-0010) |
| Ports at BASE, BASE+1 ... skipping the old web offsets | gaps with nothing behind them; nobody runs both bases' stacks side by side by number |
| A separate env file for compose ports | one more file to move and to forget; `Settings` already ignores unknown keys |
| A pytest test of the compose file | it would join the "no Docker" tier of ADR-0029, which a Docker CLI call breaks; the executed `docker compose up` is the evidence |

## Consequences
- `APP_ENV=development` refuses to boot on the example's placeholder secrets, so a copied `.env.development` must get two different 32+ character secrets before `up` (RUNBOOK).
- `postgis/postgis` is amd64 only: on Apple Silicon `db` is emulated and warns once (ADR-0030).
- Removing the stack with its volumes deletes the database and the queue; a plain `docker compose down` keeps them.
- Follow-ups: 11.3 (full-stack check), 11.4 (CI).

## Revisit when
A web client returns to this repo, a production compose is wanted, or the API needs a compose healthcheck for ordering.
