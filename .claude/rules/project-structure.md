---
description: The fixed project structure - a root app/ package laid out by layer (routers, schemas, models, services), plus core, workers and seeds - and where new code goes.
paths:
  - "app/**"
  - "tests/**"
---

# Project structure

Decided in ADR-0011 (`docs/decisions/ADR-0011-project-structure.md`); this rule repeats it so it is in front of you when you edit
`app/`. If they disagree, the ADR wins and you raise it. A change to the structure needs a new ADR (rule D1).

```
poc-base-fast-api/
├── pyproject.toml
├── alembic.ini           # Alembic config; no database URL (ADR-0017)
├── migrations/           # Alembic: env.py and hand-written revisions in versions/ (ADR-0017); tooling, not a layer
├── .env                  # secrets, never committed
├── app/
│   ├── main.py           # the app: lifespan, middleware, health, include_router; no business logic
│   ├── cli.py            # project commands that need the whole app: `python -m app.cli --export-openapi` (ADR-0020)
│   ├── config.py         # settings, validated once at boot
│   ├── dependencies.py   # shared Depends: current account, require_roles
│   ├── routers/          # one APIRouter per module
│   ├── schemas/          # Pydantic request and response models
│   ├── models/           # SQLAlchemy tables
│   ├── services/         # business logic
│   ├── core/             # cross-cutting: db, logging, errors, validation, security, cache, pagination
│   ├── workers/          # arq settings and jobs
│   └── seeds/            # seed runner and seed items
└── tests/                # unit/ and e2e/, flat test_<subject>.py files, shared helpers in utils/ (testing-python.md)
```

## Modules and where a new feature goes
1. The modules are `account`, `account_profile`, `account_role`, `auth`, `files` and `notifier`. Each has `<module>.py` in `routers/`, `schemas/`, `models/` and `services/`; the one exception is `models/`, where the files are `file.py`, `notification.py` and `system.py` (`DeletedHistory`, task 2.3, and `SeedHistory`, task 5.1). A new module adds `<module>.py` to the layers it needs; do not create a package per feature.
2. Extra files inside a layer (for example `services/otp.py`) are fine when a task names them. A new top-level module or a new layer is not: it needs an ADR (`cli.py` has ADR-0020). `cli.py` may import `main`, `config` and `core`; nothing in `app/` imports `cli`.
3. Cross-cutting code goes in `core/`, one module per concern (`core/db.py`, `core/errors.py`, ...). Do not put it in a layer.

## Import direction
4. `routers` use `services`, `schemas` and `dependencies`. `services` use `models`, `schemas`, `core` and `config`. `models` import only from `core` and from sibling models (relationships). `core` imports from no layer and may read `config`. `schemas` import nothing from `services`, `models` or `routers`. `dependencies` use `services`, `core` and `config`. `workers` use `services`, `models`, `core` and `config`; `seeds` use those and `schemas` (ADR-0023). `config` may be imported by anything except `models` and `schemas`. A module may import siblings in its own layer if there is no cycle. The full statement is in ADR-0011 and ADR-0023.
5. No business logic in a router: it parses the request, calls a service, returns a schema. A response model is never an ORM object.
6. A service never receives a framework object (request, response, headers, `Depends`). Plain values, models and Pydantic `schemas` (plain data) may go in and out (ADR-0003, ADR-0011).
7. No module imports from `routers` except `main.py`. A circular import means the logic is in the wrong layer.

## Tests
8. `tests/unit/` needs no Docker, database or network; `tests/e2e/` runs against a real Postgres and the app over HTTP. Files are flat and named `test_<module>_<layer>.py` (a router and a service called `account` never collide), `test_<concern>.py` for `core/`, or for the flow in e2e (`test_db_<module>_<layer>.py` for database tests of a module, `test_http_<subject>.py` for the client); a name is unique across both directories. Helpers are in `tests/utils/`. The rules are in `testing.md` and `testing-python.md`, the quick path in the `test-conventions` skill.

## Migrations
9. `migrations/` is tooling beside `app/`, not a layer (ADR-0017). `migrations/env.py` may import `app.config`, `app.core.db` and `app.models`; nothing in `app/` imports from `migrations/`. A revision in `migrations/versions/` imports nothing from `app`, names every table and column itself, and is never edited once merged: a schema change is a new revision.
