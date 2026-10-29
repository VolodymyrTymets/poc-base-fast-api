# Architecture

> What the system **is** and where code belongs. Structure truths only — no style preferences (those live in `.claude/rules/`).
> Update in the same PR as any structural change (rule E1).

**Status: skeleton.** Everything under "Current" exists and was run. Everything under "Planned" comes from the
scope doc, whose decisions D1–D10 are not confirmed until task 1.1 — treat it as intent, not as fact.

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
None yet: no HTTP server, no endpoint, no generated output.

### Environments
| Env | URL | Database | Who may touch it |
|-----|-----|----------|------------------|
| local | none (no server) | none | anyone |
| staging | not defined | | team |
| production | not defined | | **not the agent** (rule C5) |

## Planned (from the scope doc — unconfirmed)
- FastAPI service under `/api/v1`, Pydantic models, `api/openapi.json` as the contract (D2). The scope doc places the
  Python code in `api/`; this repo is instead a root-level project, so task 1.1 must settle the layout (D1).
- SQLAlchemy 2 async + asyncpg + Alembic on Postgres/PostGIS, table and column names kept identical to the Node
  base's Prisma schema (D3). Redis as a derived read cache and as the arq job-queue backend (D4).
- Packages by feature: account, account_profile, account_role, auth, files, notifier, workers, seeds, common, db.
- Tests against a testcontainers `postgis/postgis` database with one migrated template per run (D8).
- Reference implementation to port from: the Node `poc-base` repo (NestJS + GraphQL + Prisma), 14 GraphQL operations
  that become REST routes (task 1.2).

## Key flows
None implemented. The flows to port (OTP sign-in, password sign-in and restore, file upload, token refresh) are
described in the Node base's `docs/ARCHITECTURE.md`; the REST versions are specified by tasks 7.1–7.6 and 8.2–8.3 of the scope doc.

## External integrations
| Service | Purpose | Failure mode | Sandbox available? |
|---------|---------|--------------|--------------------|
| none yet | SMS and email stay log-only (out of scope) | — | — |

## Known constraints and landmines
- The scope doc says Python 3.12 (task 1.3, `python:3.12-slim`); this repo pins 3.14 (ADR-0002). Docker tasks must use the pinned version.
- The scope doc assumes `api/` as the Python root. Commands in `CLAUDE.md` assume the repo root.
- `uv.lock` is committed; `.venv/` and `dist/` are not.
