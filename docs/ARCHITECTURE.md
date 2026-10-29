# Architecture

> What the system **is** and where code belongs. Structure truths only — no style preferences (those live in `.claude/rules/`).
> Update in the same PR as any structural change (rule E1).

**Status: skeleton with decisions recorded.** "Current" exists and was run. "Decided" is settled by ADR-0003 to ADR-0010 but not yet
built. "Planned" is still intent from the scope doc and is decided by the task named beside it.

## Current

### Repo layout
| Path | What lives here | Deployable? | Owner |
|------|-----------------|-------------|-------|
| `src/poc_base_fast_api/` | the importable package; `__init__.py` holds only the `uv init` `main()` that prints a greeting | no | backend |
| `pyproject.toml` | project metadata, `requires-python >=3.14`, empty `dependencies`, script `poc-base-fast-api`, build backend `uv_build` | — | backend |
| `uv.lock`, `.python-version` | lockfile (uv-owned) and the interpreter pin (3.14) | — | generated / backend |
| `docs/`, `.claude/`, `.github/` | agent config, knowledge docs, PR template and the evidence-check workflow | — | backend |

There is a single package in a `src` layout at the repo root. No `api/` or `web/` directory exists.

### Where data truth lives
Nothing is persisted yet. No database, cache or queue is wired.

### Boundaries and contracts
The REST contract is written down in [docs/api/ENDPOINTS.md](api/ENDPOINTS.md); no server, endpoint or generated output exists yet.

### Environments
| Env | URL | Database | Who may touch it |
|-----|-----|----------|------------------|
| local | none (no server) | none | anyone |
| staging | not defined | | team |
| production | not defined | | **not the agent** (rule C5) |

## Decided (ADR-0003 to ADR-0010, built by the scope-doc tasks)
Supersession applies to this repo only; the Node repo's ADRs stay in force there.

- REST with FastAPI under `/api/v1`, Pydantic models, error body `{"error": {...}}`, contract exported to a root `openapi.json`
  with a stale-spec test ([ADR-0003](decisions/ADR-0003-rest-api-fastapi-openapi.md)).
- SQLAlchemy 2 async + asyncpg + Alembic on Postgres/PostGIS, Prisma table and column names as a target proven by task 2.5
  ([ADR-0004](decisions/ADR-0004-data-layer-sqlalchemy-alembic.md)).
- arq worker on Redis, a separate process; retries by `Retry(defer=...)`
  ([ADR-0005](decisions/ADR-0005-job-queue-arq.md)).
- Tests on a real PostGIS Postgres through testcontainers, one template database per run
  ([ADR-0006](decisions/ADR-0006-test-database-testcontainers.md)).
- ruff, mypy strict, pytest, installed in task 1.4 ([ADR-0007](decisions/ADR-0007-quality-tooling-ruff-mypy-pytest.md)).
- Refresh tokens stored as sha256, sent in `x-refresh-token`
  ([ADR-0008](decisions/ADR-0008-auth-tokens-refresh-hash-and-transport.md)).
- Files as multipart upload and authenticated download, bytes in Postgres
  ([ADR-0009](decisions/ADR-0009-file-transfer-multipart.md)).
- Root-level `src/poc_base_fast_api/` package, API only, `APP_ENV` configuration
  ([ADR-0010](decisions/ADR-0010-repo-layout-and-configuration.md)).

## Planned (intent from the scope doc, not yet decided)
- Redis as a derived read cache (task 9.1 decides it; Redis is also the arq queue backend, so flushing it drops in-flight jobs).
- Packages by feature: account, account_profile, account_role, auth, files, notifier, workers, seeds, common, db.
- Reference implementation to port from: the Node `poc-base` repo (NestJS + GraphQL + Prisma), 14 GraphQL operations that
  become REST routes (task 1.2).

## Key flows
None implemented. The flows to port (OTP sign-in, password sign-in and restore, file upload, token refresh) are
described in the Node base's `docs/ARCHITECTURE.md`; the REST versions are specified by tasks 7.1–7.6 and 8.2–8.3 of the scope doc.

## External integrations
| Service | Purpose | Failure mode | Sandbox available? |
|---------|---------|--------------|--------------------|
| none yet | SMS and email stay log-only (out of scope) | — | — |

## Known constraints and landmines
- The scope doc still says Python 3.12 (task 1.3, `python:3.12-slim`); [ADR-0002](decisions/ADR-0002-python-3-14.md) pins 3.14 and wins. Docker tasks must use the pinned version.
- The scope doc still says `api/`, `app/` and ADR-P0x, and has web tasks (package 10, task 11.3); [ADR-0010](decisions/ADR-0010-repo-layout-and-configuration.md) puts the package at the repo root and drops `web/`. The commands in `CLAUDE.md` assume the repo root.
- `uv.lock` is committed; `.venv/` and `dist/` are not.
