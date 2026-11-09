# POC-11.2 — docker-compose.yml, set-ports.sh, move-env.sh

## Problem
Task 11.1 built the API and worker images, but starting the stack still means four hand-typed `docker run` commands (Postgres, Redis, API, worker) with matching
environment. The Node base solved this with `docker-compose.yml`, `set-ports.sh` (a second stack on non-colliding host ports) and `move-env.sh` (carry the
gitignored env files into another checkout); the scope doc's rows 11.2 and D9 say they keep working here.

## Goal / business value
Goal 1 (scaffolding): `docker compose up -d` is the whole first run for a fork, and a second copy of the stack (a worktree) can run beside the first.

## Scope
- in: `docker-compose.yml` (services `db`, `redis`, `api`, `worker`); `set-ports.sh`; `move-env.sh`; `POSTGRES_*` lines in `.env.development.example` (the database container reads them);
  commented `EXPOSE_*` lines in `.env.example`; RUNBOOK "Docker Compose" section; ARCHITECTURE rows; ADR-0031.
- **out (explicit):** `web-app` and `web-admin` services (no `web/`, ADR-0010; this is why the scope doc's "six services" is four here); the full-stack check with a client (11.3); CI (11.4);
  bind mounts or hot reload for the API; a compose healthcheck for the API; production compose; changing the Dockerfile or the entrypoint.

## Acceptance criteria
- [ ] AC1 Given `.env.development` copied from the example, with secrets set, when `docker compose up -d --build`, then `db`, `redis`, `api` and `worker` run, `db` and `redis` report healthy first, and `GET /api/v1/health` answers on the host.
- [ ] AC2 Given the stack is up, when the OTP request/verify flow is called, then the SMS job runs in the `worker` container (its log shows `[SMS] TOTP code sent to ***`): the API and the worker share Redis.
- [ ] AC3 `./set-ports.sh 4000` writes `EXPOSE_API_PORT`, `EXPOSE_POSTGRES_PORT` and `EXPOSE_REDIS_PORT` (4000, 4001, 4002) to `.env`, and `PORT`, `REDIS_PORT` and the `DATABASE_URL` port to `.env` for a non-docker run; container-internal ports never change; running it twice gives the same file; a bad argument exits 1 with the usage and writes nothing.
- [ ] AC4 A second checkout, given its env files by `move-env.sh` and its ports by `./set-ports.sh 4000`, runs `docker compose up -d` beside the first stack, and both answer `/api/v1/health` on their own ports.
- [ ] AC5 `move-env.sh <dir>` copies `.env`, `.env.development` and `.env.test` that exist, says which it skipped, fails with usage when `<dir>` is missing or not a directory, and refuses to overwrite a file already in `<dir>` unless `--force` is given.
- [ ] AC6 No secret in `docker-compose.yml`; the files it reads are gitignored; `docker compose config` is valid after the examples are copied to `.env.development`.
- [ ] AC7 The RUNBOOK's Docker Compose section, followed verbatim, gives a running stack.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| `.env.development` missing | `docker compose up` fails naming the file (compose's `env_file` is required), the RUNBOOK says to copy the example | assumption |
| `.env.development` has the placeholder secrets and `APP_ENV=development` | `api` and `worker` stop at boot (ADR-0010 boot check); RUNBOOK says to set two 32+ character secrets | existing behaviour |
| `set-ports.sh` run from another directory | works on the repo root (`cd "$(dirname "$0")"`) | Node script |
| `.env` has no trailing newline, or already has the key | the key is replaced in place or appended on its own line | Node script (awk pass), kept |
| `DATABASE_URL` absent from `.env` | not invented: only an existing port is rewritten | Node script, kept |
| Apple Silicon | `postgis/postgis` is amd64 only, so `db` is emulated (ADR-0030 already records it) | ADR-0030 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | Service name of Postgres | `db`, because `.env.development.example` already points `DATABASE_URL` at host `db` | no |
| A2 | Host-port scheme without web | contiguous from the base: API = BASE, Postgres = BASE+1, Redis = BASE+2 (the Node base kept web at BASE and skipped numbers); `./set-ports.sh 4000` gives 4000/4001/4002 | yes, confirm |
| A3 | One `.env` for both compose interpolation and a local non-docker run | yes, as `set-ports.sh` of the Node base did with `.env` plus `api/.env`; here there is no `api/`, `Settings` ignores `EXPOSE_*` (`extra="ignore"`), and compose does not pass `.env` into containers | yes, confirm |
| A4 | Env file the containers read | `.env.development` (matches `APP_ENV=development` and the existing example), not `.env` | no |
| A5 | "six services" in the scope doc | four; the two web services are gone (D10 dropped) | no |
