# POC-11.2 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code. -->
Approved-by: Volodymyr - 2026-11-09 (approved in chat, including A2 and A3)

Pattern followed: the Node base's `docker-compose.yml`, `set-ports.sh` and `move-env.sh` (read in `../poc-base`, not copied wholesale: the web services, `api/` paths and GraphQL URLs go),
`tests/e2e/test_wait_for_postgres.py` for process-level tests of a script, `.env.development.example` for the variable list. The `Dockerfile` and entrypoint of POC-11.1 are used as they are.
The compose file is a new kind of file here, recorded in ADR-0031 (rule D1).

## Contract changes
- boundary: none; `openapi.json` must not change.
- config: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` in `.env.development.example` (read by the `db` container; `Settings` ignores them); `EXPOSE_API_PORT`, `EXPOSE_POSTGRES_PORT`, `EXPOSE_REDIS_PORT` (compose interpolation only, defaults 3001/5432/6379).
- dependencies: none. `uv.lock` untouched.
- generated output: none.

## Requirements (ordered; branch `feat/POC-11.2-compose-and-ports`, one draft PR, one commit each)

### R1 — `docker-compose.yml` (M)
- first step (riskiest unknown): `docker compose config` and a bare `docker compose up -d db redis` before the app services are added.
- files: `docker-compose.yml`, `.env.development.example` (`POSTGRES_*`, and its header: it is copied to `.env.development`, which the compose stack reads), `.env.example` (commented `EXPOSE_*`).
- services: `db` (`postgis/postgis:16-3.4`, `env_file: .env.development`, healthcheck `pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"`, volume `pgdata`, port `${EXPOSE_POSTGRES_PORT:-5432}:5432`), `redis` (`redis:7-alpine`, `redis-cli ping` healthcheck, volume `redisdata`, port `${EXPOSE_REDIS_PORT:-6379}:6379`),
  `api` (`build: {context: ., target: development}`, `env_file: .env.development`, port `${EXPOSE_API_PORT:-3001}:3001`, `depends_on` both `service_healthy`), `worker` (`target: worker`, same env file and dependencies, no port). One bridge network, as in the Node file; no `version:` key (obsolete in Compose v2).
- layer: infra (ask-first path `**/docker-compose*.yml`: confirm when the hook asks).
- test: none as a pytest file. A test that shells out to `docker compose config` would join the "no Docker" tier (ADR-0029, `tests/utils/markers.py` marks by fixtures only) and a new marker needs a superseding ADR (B4). Evidence is the executed runs below plus, for AC6, `grep` of the file for secrets and `docker compose config` output in the PR body.
- evidence: redact the OTP code and JWTs from any pasted curl output (A6, D8).
- executed how: `cp .env.development.example .env.development`, set two secrets, `docker compose up -d --build`, `docker compose ps` (healthy), `curl localhost:3001/api/v1/health`, OTP request/verify with `curl`, `docker compose logs worker` shows `[SMS] TOTP code sent to ***` (AC1, AC2), `docker compose down`.

### R2 — `set-ports.sh` (S)
- files: `set-ports.sh` (POSIX sh, `set -eu`, `cd "$(dirname "$0")"`): validates 1024-65530, derives API = BASE, Postgres = BASE+1, Redis = BASE+2 (A2), writes the three `EXPOSE_*` to `.env`, and `PORT`, `REDIS_PORT`, and the port of `DATABASE_URL` (only when the line exists) to `.env`; keeps the Node `set_kv` single awk pass and `set_url_port`. Prints what it derived. Executable bit set.
- layer: tooling at the repo root beside `docker-compose.yml`.
- test: `tests/e2e/test_set_ports_script.py` (no Docker, runs in the `-m "not db and not redis"` tier) copies the script to a temp dir and runs it there as a process: values for base 4000; idempotent second run (file bytes equal); a `.env` with no trailing newline; an existing `DATABASE_URL` port rewritten and the host, password and database name kept; no `DATABASE_URL` line means none is added; non-numeric, 1023 and 65531 exit 1 with usage and no `.env` written; run from another cwd writes next to the script. No Docker.
- executed how: run it in a scratch copy and `cat .env`; run with `abc`, `80`, `70000`.

### R3 — `move-env.sh` (S)
- files: `move-env.sh` (`set -eu`, quoted paths): usage and exit 1 without an argument or when it is not a directory; copies each of `.env`, `.env.development`, `.env.test` that exists in the repo root, refuses (exit 1, nothing copied) when any of them already exists in the target unless `--force` is given (a silent overwrite could wipe the other checkout's secrets), prints `copied X` or `skipped X (not found)`; exit 0 even when some are missing, exit 1 when none exist (nothing to move is probably a wrong directory). Executable bit set.
- test: `tests/e2e/test_move_env_script.py`: all three copied byte for byte; one missing is skipped and named; none present exits 1; missing or non-directory argument exits 1; the source files are unchanged. No Docker.
- executed how: as in AC4, with a real second checkout.

### R4 — second stack check (S, no code)
- executed how (AC4): `git worktree add ../poc-base-fast-api-second`, `./move-env.sh ../poc-base-fast-api-second`, in it `./set-ports.sh 4000`, `docker compose up -d --build` while the first stack is up, curl both health URLs, `docker compose down` in both, remove the worktree. Paste the output.

### R5 — docs and ADR (S)
- files: `docs/decisions/ADR-0031-compose-stack-and-ports.md` (four services and why not six, `db` name, one `.env.development` for containers, `.env` for interpolation and a local run, port scheme, no API healthcheck or bind mount), `docs/RUNBOOK.md` ("Docker Compose" section, and the pointer in "Docker"; the `POSTGRES_*` variables), `docs/ARCHITECTURE.md` (layout rows, Decided bullet, Known landmines: the scope doc's "six services"), `README.md` if it lists commands, RUNBOOK note that `PORT` in `.env` is the published API port so a local run and the `api` container cannot share a checkout, `docs/features/POC-11.2/spec.md` ACs ticked.
  `CLAUDE.md` command map and `.claude/rules/project-structure.md` (root layout) are ask-first paths: edited only with the human's OK, otherwise proposed in the PR body. ADR-0031 also says why the scripts sit at the root and not in `scripts/` (acceptance calls `./set-ports.sh`, D9).
- executed how: follow the RUNBOOK section verbatim once.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest -m "not db and not redis"` (the two new script test files run here), `uv run python -m app.cli --export-openapi --check`, `uv build`, and the compose runs above.

## Docs to update in this PR
- [ ] docs/features/POC-11.2/spec.md (ACs)
- [ ] docs/ARCHITECTURE.md — new root files
- [ ] docs/RUNBOOK.md — Docker Compose section
- [ ] docs/decisions/ADR-0031
- [ ] docs/DOMAIN_GLOSSARY.md — none (no new domain term)
- [ ] the scope doc row 11.2 status; it says six services and `api/` paths (E2: stale, noted in the PR body, the doc is not in the repo's tracked files)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| `.env.development` placeholders fail the `development` boot check | `api` restarts, looks like a compose bug | R1 first run with the placeholders, then with real secrets; RUNBOOK says so |
| `postgis/postgis` amd64 image emulated on Apple Silicon is slow to become healthy | healthcheck retries too few | run it here (Darwin) in R1; raise `retries`/`start_period` if it flaps |
| `.env` doubles as the app's local env and compose interpolation | a stray `EXPOSE_*` breaks nothing (`extra="ignore"`), but `PORT` set by `set-ports.sh` differs from the container's 3001 | covered by A3 and an assertion that the container-side port stays 3001 |
| Port from `set-ports.sh` already in use on the host | `up` fails on bind | not detected by the script (as in Node); RUNBOOK names the symptom |
| Compose tests need the Docker CLI | fails on a machine without it | message names Docker; same stance as 11.1 |

## Assumptions
- A1-A5 of the spec; whoever writes `Approved-by:` also confirms A2 (port scheme) and A3 (one `.env`).

## Estimate
R1 M · R2 S · R3 S · R4 S · R5 S
