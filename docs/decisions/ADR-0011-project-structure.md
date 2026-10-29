# ADR-0011 — Root `app/` package, laid out by layer

- **Date:** 2026-10-29
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-1.3
- **Supersedes:** the package location in ADR-0010 (`src/poc_base_fast_api/`). The rest of ADR-0010 stands: API only, `APP_ENV`, the environment variable names and the single `JWT_SECRET`. Task 1.3 of the scope doc (row text of rev 114).

## Context
ADR-0010 put the Python package in `src/poc_base_fast_api/` and left its inner layout open. The scope doc then fixed the structure in task 1.3:
a root `app/` laid out by layer, with the other tasks' file paths rewritten to match (`app/core/db.py`, `app/models/file.py`,
`app/services/otp.py`, `app/routers/auth.py`). Until one layout is recorded, the ADR and the plan disagree.

## Decision
- The package is `app/`, at the repo root, with no `src/` directory. The uv build backend is told so with `[tool.uv.build-backend]`, `module-name = "app"` and `module-root = ""`. The console script `poc-base-fast-api` points at `app:main`.
- `app/` is laid out by layer. Every module of the Node base becomes one file in each layer: `routers/<module>.py` (an `APIRouter`), `schemas/<module>.py` (Pydantic request and response models), `models/<module>.py` (SQLAlchemy tables) and `services/<module>.py` (business logic). The modules are `account`, `account_profile`, `account_role`, `auth`, `files` and `notifier`. The one exception is `models/`, whose two files are named `file.py` and `notification.py`, as task 2.3 cites them.
- Cross-cutting code (DB session, errors, logging, validation, JWT, cache, pagination) lives in `app/core/`, one module per concern. Shared `Depends` are in `app/dependencies.py`, settings in `app/config.py`, the application and its router wiring in `app/main.py`, background jobs in `app/workers/`, seed items in `app/seeds/`.
- **Import direction:**
  - routers use services, schemas and dependencies; services use models, schemas, core and config; models import only from core (and from sibling models, for relationships); `core` imports from no layer and may read `config`; `schemas` import nothing from services, models or routers.
  - `dependencies` uses services, core and config. `workers` and `seeds` use services, models, core and config. `main.py` wires: it builds the app, installs lifespan, middleware and the health route, and includes the routers. `config` may be imported by anything except `models` and `schemas`.
  - A module may import its siblings in the same layer (for example a service calling another service) as long as there is no cycle.
  - Business logic is never in a router. A service never receives a framework object (request, response, headers, `Depends`); Pydantic `schemas` are plain data and may be passed in and out (ADR-0003 keeps transport objects out of services, not data models).
- The layout inside `tests/` is set by task 3.3, not here. `.env` is never committed; `.env.example` lists the variables.
- A new top-level module or a new layer needs an ADR. The rule `.claude/rules/project-structure.md` repeats this structure and cites this ADR for it.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| `src/poc_base_fast_api/` with one package per feature (ADR-0010 as written) | no longer matches the scope doc's file paths, and it left the inner layout open |
| Feature-sliced `app/<feature>/router.py`, `models.py`, `service.py` | the scope doc's tasks cite the layered paths, and a layered tree keeps each kind of code in one place |
| `api/` subdirectory | no second workspace to separate it from (ADR-0010) |

## Consequences
- Positive: each kind of code has one obvious place; the rule file can enforce it; the import direction is explicit.
- Accepted cost: `app` is a generic top-level name that would collide if installed beside another project's `app`, which is fine for an application deployed alone. Some of the 24 layer files will have no content, because not every module needs a router or a schema; their docstrings say so and a later PR may delete them.
- Follow-ups: the scope doc's first half of row 1.3 (copy `web/`, compose files, work in `api/`) and the dated note about reading `app/` as `src/poc_base_fast_api/` are stale and need a hand edit.

## Revisit when
A second deployable is added to this repo, or a layer grows large enough that one folder per feature becomes easier to navigate.
