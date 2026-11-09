# poc-base-fast-api

An internal starter kit for new client POCs: a Python 3.14 + FastAPI REST API (`/api/v1`) with password and OTP sign-in, JWT access and refresh tokens, roles,
file storage in Postgres, seed data, an arq background worker and a real-database test base. It is the Python counterpart of the Node/GraphQL `poc-base`. API only: there is no web client.

## Run it with Docker (nothing else needed on the host)
```bash
cp .env.development.example .env.development   # then set JWT_SECRET and JWT_REFRESH_TOKEN_SECRET to two different 32+ character values
docker compose up -d --build
curl localhost:3001/api/v1/health               # {"status":"ok"}
```
This starts Postgres (PostGIS), Redis, the API and the worker. More, including a second stack on other ports: [RUNBOOK, "Docker Compose"](docs/RUNBOOK.md).

## Run it with uv
```bash
uv sync                          # Python 3.14 is fetched if missing
cp .env.example .env
uv run alembic upgrade head      # needs a PostGIS database; see the RUNBOOK "First run" for one
uv run poc-base-fast-api         # the API on PORT (default 3001)
uv run arq app.worker.WorkerSettings   # the worker (needs Redis)
```

## Check it
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -m "not db and not redis"   # no Docker needed; `uv run pytest` runs everything (needs Docker)
```
CI runs the same checks on every pull request.

## Where to read next
- [docs/RUNBOOK.md](docs/RUNBOOK.md): how to run, test and troubleshoot everything.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): what exists and where code belongs.
- [docs/api/ENDPOINTS.md](docs/api/ENDPOINTS.md) and [docs/api/ERRORS.md](docs/api/ERRORS.md): the REST contract; the generated one is `openapi.json`.
- [docs/decisions/](docs/decisions/): the ADRs. [CLAUDE.md](CLAUDE.md) and [.claude/rules/](.claude/rules/): the rules for contributors and agents.
