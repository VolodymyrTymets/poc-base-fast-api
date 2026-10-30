# ADR-0012 — The console script starts the server

- **Date:** 2026-10-30
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-1.4 (with POC-1.5)
- **Supersedes:** only the sentence of ADR-0011 that says the console script `poc-base-fast-api` points at `app:main`. The rest of ADR-0011 stands.

## Context
ADR-0011 kept the `uv init` stub: `poc-base-fast-api = "app:main"` printed a greeting. Task 1.5 needs a way to start the API on `PORT`, and the
ruff rule `T20` (ADR-0007) rejects the stub's `print`. The command map in `CLAUDE.md` wants one dev-server command.

## Decision
- The greeting stub is removed from `app/__init__.py`, which keeps only its docstring.
- Task 1.4 drops the `[project.scripts]` entry; task 1.5 adds it back as `poc-base-fast-api = "app.main:run"`.
- `app.main:run` calls uvicorn with the app factory `app.main:create_app` on the `PORT` setting. `uv run poc-base-fast-api` is the dev-server command.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Keep `app:main` and have it start the server | `app/__init__.py` would import FastAPI and settings for every `import app` |
| Document `uv run uvicorn app.main:create_app --factory --port 3001` as the command | the port would be written twice, once in settings and once in the command |
| Keep the greeting as a smoke command | it needs a `print`, which the lint rule forbids, and it checks nothing |

## Consequences
- Positive: one command starts the server and reads the same settings as the app.
- Accepted cost: between the 1.4 commit and the 1.5 commit of this PR no console script exists; `docs/RUNBOOK.md` is updated in the same PR.
- Follow-ups: tasks 1.5 and 11.1 (the container command).

## Revisit when
A second deployable (a worker entry point, task 6.1) needs its own script name.
