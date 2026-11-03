# POC-4.1 — Router layout and exported OpenAPI contract

## Problem
The six feature routers (`account`, `account_profile`, `account_role`, `auth`, `files`, `notifier`) are docstring-only and `main.py` does not include them,
so tasks 5.x to 8.x have no place to add routes. The contract named by ADR-0003 (`openapi.json`, stale-spec test) does not exist, and nothing prevents a
route from returning an ORM object.

## Goal / business value
Goal 1 (scaffolding): a fork adds a route by editing one router file; the contract is visible in `/docs` and committed.

## Scope
- in: one `APIRouter` per feature module with a tag, all included under `/api/v1`; tag metadata in the app; a command that exports `openapi.json` at the repo root;
  a test that fails when the committed file is stale; a test that no route's response model is an ORM class; `openapi.json` added to `protected-paths.md`.
- **out (explicit):** any new endpoint (health stays the only route, P3); the error contract (4.2); validation (4.3); auth dependencies (4.4); a CI step for the stale check (11.4, T4);
  a health router (not a module in ADR-0011).

## Acceptance criteria
- [x] AC1 Given the running app, when `/docs` and `/openapi.json` are opened, then the six tags are listed and `GET /api/v1/health` is documented.
- [x] AC2 Given each module in `routers/`, then it defines `router = APIRouter(prefix=..., tags=[...])`, and `create_app` includes it under `/api/v1`.
- [x] AC3 Given `uv run python -m app.cli --export-openapi`, then `openapi.json` is written deterministically (sorted keys, trailing newline); a second run changes nothing.
- [x] AC4 Given a route added without regenerating, then the stale-spec test fails with the command to run; with the file regenerated it passes.
- [x] AC5 Given a route whose response model is a `Base` subclass, then the response-model test fails.
- [x] AC6 Given the diff, then `openapi.json` is in `protected-paths.md` (never hand-edited) and ARCHITECTURE, RUNBOOK and CLAUDE.md command map are updated.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Settings differ (env, DATABASE_URL) | spec is identical: it must not depend on settings | assumption A2 |
| An empty router | adds no path; its tag is still listed through `openapi_tags` | assumption A3 |
| Spec generated on another Python/FastAPI patch | pinned by `uv.lock`; a drift is a real stale signal | none needed |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Export command shape | `uv run python -m app.cli --export-openapi` (`--check` verifies), like `python -m app.seeds`; no console script, so `pyproject.toml` is untouched | no, but CLAUDE.md gets a new map row |
| Q2 | Router prefixes | module-level, e.g. `/auth`; `account_profile` uses `/accounts` (ENDPOINTS.md, 5.4); `account` `/account`, `account_role` none yet, `files` `/files`, `notifier` none: an empty router with its tag, included like the others (decided) | no |
