# POC-11.1 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code. -->
Approved-by: Volodymyr - 2026-11-09

Pattern followed: `app/main.py` `run()` (console script, JSON logging via `configure_logging`; a container must use it, RUNBOOK "Logging"), `app/config.py` for the new
setting, `tests/e2e/test_db_seed_entrypoints.py` for process-level tests of commands, `.env.example` for documenting variables. No Dockerfile precedent exists in this repo (the Node one is not copied here): the layout is new but
config-only, so no ADR beyond the one in R4.

## Contract changes
- boundary: none; `openapi.json` must not change.
- config: new env `HOST` (default `127.0.0.1`) read by `run()`; entrypoint-only variables `DB_WAIT_ATTEMPTS`, `DB_WAIT_INTERVAL_SECONDS`, `RUN_MIGRATIONS` (not in `Settings`).
- dependencies: none (asyncpg is already runtime). `uv.lock` untouched.
- generated output: none.

## Requirements (ordered; branch `feat/POC-11.1-dockerfile`, one draft PR, one commit each)

### R1 — `HOST` setting (S)
- files: `app/config.py` (`host: str = Field(default="127.0.0.1", min_length=1)`), `app/main.py` (`uvicorn.run(host=settings.host, ...)`), `.env.example`, `.env.development.example`.
- layer: config / entrypoint.
- test: `host` cases added to `tests/unit/test_config.py` (default, override, blank rejected naming the field); `tests/unit/test_run.py` asserts `host=settings.host` reaches uvicorn. `tests/e2e/test_shutdown.py` stays green (default unchanged).
- executed how: `HOST=0.0.0.0 uv run poc-base-fast-api` then `curl localhost:3001/api/v1/health`; show `netstat`/`lsof` listening address.

### R2 — wait for Postgres (S)
- files: `scripts/wait_for_postgres.py` (reads `DATABASE_URL`, strips the `+asyncpg` driver, `asyncpg.connect` in a loop of exactly N attempts, prints `attempt i/N failed: <exception class>` never the URL or password, exit 0 / 1 / 2 for missing URL). mypy `files` gains `scripts` (ask-first path `pyproject.toml`).
- layer: tooling beside `app/`, not in the wheel (as `migrations/`); a new top-level `scripts/` imports nothing from `app`. It is not in `app/cli.py` (ADR-0020) because it must run before the app's settings and migrations are usable, and it needs no app code. Recorded in ADR-0030 and an ARCHITECTURE layout row.
- test: `tests/e2e/test_wait_for_postgres.py`: (a) unreachable port, `ATTEMPTS=3`, interval 0.1 → exit 1, exactly 3 `attempt` lines, URL password absent from output; (b) the test database → exit 0 on attempt 1; (c) no `DATABASE_URL` → exit 2; (d) the default: `DB_WAIT_ATTEMPTS` unset, `DB_WAIT_INTERVAL_SECONDS=0`, dead port → exit 1, exactly 30 lines `attempt i/30 failed: ...` and a final message naming 30 (issue I.6). Only (b) needs Docker.
- executed how: run it by hand against the compose-less `postgis` container and against a dead port; paste output.

### R3 — Dockerfile, entrypoint, `.dockerignore` (M)
- first step of the branch (riskiest unknown): a Dockerfile with only the `base` stage, `docker build --target base .`, before R1.
- files: `Dockerfile` (stages `base`, `development`, `worker`; base `python:3.14-slim`, `ENV PATH=/app/.venv/bin:$PATH` so `poc-base-fast-api`, `alembic` and `arq` resolve, uv copied from the pinned `ghcr.io/astral-sh/uv` image tag, `UV_COMPILE_BYTECODE=1`, deps layer cached before source: `uv sync --locked --no-install-project`, then source, then `uv sync --locked`; non-root `app` user; `ENV HOST=0.0.0.0 PYTHONUNBUFFERED=1`; `ENTRYPOINT ["./docker-entrypoint.sh"]`; stage `development` (dev group, `CMD ["poc-base-fast-api"]`) and stage `worker` (`--no-dev`, `ENV RUN_MIGRATIONS=0`, `CMD ["arq","app.worker.WorkerSettings"]`)), `docker-entrypoint.sh` (`set -eu`; require `DATABASE_URL`; `python scripts/wait_for_postgres.py`; when `RUN_MIGRATIONS` ≠ 0: `alembic upgrade head`, `python -m app.seeds`; `exec "$@"`), `.dockerignore` (`.venv`, `.git`, `dump.rdb`, `.serena`, `.env*` except examples, caches, `dist`, `docs`, `tests` stays: development runs tests), `.gitignore` unchanged.
- layer: infra (ask-first paths `**/Dockerfile`: confirm when the hook asks).
- test: `tests/e2e/test_docker_image.py`. Every test, and the session build fixture, requests `database_url`, so the marker is `db` and `-m "not db and not redis"` never selects it (option (a): no new marker). It fails, never skips, with a Docker message. The container reaches the test Postgres through `host.docker.internal` with `--add-host=host.docker.internal:host-gateway` (works on Linux and Docker Desktop), the URL host rewritten from `localhost`. Tests: health answers and the roles exist (AC2); non-root; AC5: a plain `postgres:16` (no PostGIS) makes `alembic upgrade head` fail, the container exits non-zero and the server never started; AC7: `ls -a` shows no `.env` and `docker inspect` `Env` holds no secret value. One session-scoped build fixture (slow).
- executed how: `docker build --target development -t poc-api .`; `docker build --target worker -t poc-worker .`; `docker run` the API with `DATABASE_URL` pointing at a PostGIS container, curl health, `docker stop` and show the exit status from `docker inspect`: observed 0 (uvicorn handles SIGTERM itself as PID 1; 143 would be a shell's status for a killed process, 137 a SIGKILL after the 10 s grace) and that it stops well inside 10 s; run the worker with a Redis container and show the JSON startup line; run with a wrong DB host and show a wrong DB host with `DB_WAIT_INTERVAL_SECONDS=0` and the default, exactly 30 `attempt i/30` lines then exit 1; also the PostGIS-less Postgres failure (AC5) and `docker inspect` Env / `ls -a` (AC7).

### R4 — docs and ADR (S)
- files: `docs/decisions/ADR-0030-container-image.md` (stages, entrypoint owns wait/migrate/seed, worker never migrates, `HOST`, the `scripts/` directory and its import rule), `docs/RUNBOOK.md` ("Docker" section: build, run, variables, the `exec` and SIGTERM note), `docs/ARCHITECTURE.md` (repo layout rows for the Dockerfile files and `scripts/`, Decided bullet), `README.md` if it lists commands, `docs/features/POC-11.1/spec.md` ACs ticked.
- executed how: follow the RUNBOOK section verbatim once.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest -m "not db and not redis"`, `uv run pytest tests/e2e` (Docker), `uv run python -m app.cli --export-openapi --check`, `uv build`, the docker builds above.

## Docs to update in this PR
- [ ] docs/features/POC-11.1/spec.md (ACs)
- [ ] docs/ARCHITECTURE.md — new root files, `HOST`
- [ ] docs/RUNBOOK.md — Docker section; the "container command must use the console script" line gets its fulfilment
- [ ] docs/decisions/ADR-0030
- [ ] docs/DOMAIN_GLOSSARY.md — none (no new domain term)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| `python:3.14-slim` or a wheel (asyncpg, argon2-cffi) not available for 3.14/aarch64 | build fails | `docker build --target base .` first in R3, before the entrypoint |
| docker image test is slow in CI-less runs | developers skip it | one build per session, only in `tests/e2e`; unit tier unaffected |
| Redis-down/DB-down behaviour of the app unchanged, but the entrypoint hides a bad `DATABASE_URL` format | confusing failure | script prints the exception class, tested in R2 |
| seeds run twice (entrypoint and lifespan) | none: idempotent under an advisory lock (RUNBOOK "Seeds") | stated; the entrypoint run gives the exit status |

## Assumptions
- A1–A5 of the spec; whoever writes `Approved-by:` also confirms A2 (the `HOST` setting, outside the scope-doc row); the uv image tag is pinned to the version in `uv --version` locally.

## Estimate
R1 S · R2 S · R3 M · R4 S
