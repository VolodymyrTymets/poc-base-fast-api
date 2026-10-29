# ADR-0010 — Root-level API-only repo and environment-based configuration

- **Date:** 2026-10-29
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-1.1
- **Supersedes:** Node ADR-0008 (Web app scaffold) and Node ADR-0012 (Web auth client), because this repo has no `web/`. It amends Node ADR-0009 (Configurable ports): only the environment variable names carry over; Docker Compose and `set-ports.sh` belong to task 11.2. Decisions D1, D9 and D10 of the scope doc.

## Context
The scope doc proposed a new repo with Python under `api/` and `web/` copied beside it. The repo that exists is a root-level `uv` project
(`src/poc_base_fast_api/`). volodymyr decided on 2026-10-29 that only the API is built here.

## Decision
- The Python package is `src/poc_base_fast_api/`, at the repo root. There is no `api/` and no `web/`. Wherever the scope doc says `app/` or `api/`, read the package path and the repo root.
- D10 (a web REST client) is dropped with `web/`.
- Configuration comes from the environment, validated once at boot with pydantic-settings. `NODE_ENV` becomes `APP_ENV`; `DATABASE_URL`, `REDIS_*`, `PORT`, `JWT_*`, `CORS_ORIGINS` and `FILE_*` keep their names.
- One `JWT_SECRET` signs access tokens. The Node base's separate `JWT_ACCESS_TOKEN_SECRET` only worked through a fallback to `JWT_SECRET`, and was in no template.
- The access-token default lifetime is 15 minutes, and the env template says so.
- Env files are never committed (rule A6); `.env.example` lists the variables.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| `api/` subdirectory | no second workspace to separate it from |
| Copying `web/` into this repo | out of scope; the scope doc's web tasks (package 10) do not apply |
| Keeping `NODE_ENV` | misleading in a Python service |

## Consequences
- Positive: the command map stays plain `uv ...` from the repo root.
- Accepted cost: the scope doc's paths and task 1.3 no longer match; the doc needs editing, and package 10 and task 11.3 no longer apply.
- Follow-ups: tasks 1.3 and 1.5 build the package and settings module.

## Revisit when
A frontend is added to this repo, or a second deployable needs its own directory.
