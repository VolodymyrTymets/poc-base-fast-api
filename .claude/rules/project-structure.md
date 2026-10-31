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
│   ├── config.py         # settings, validated once at boot
│   ├── dependencies.py   # shared Depends: current account, require_roles
│   ├── routers/          # one APIRouter per module
│   ├── schemas/          # Pydantic request and response models
│   ├── models/           # SQLAlchemy tables
│   ├── services/         # business logic
│   ├── core/             # cross-cutting: db, logging, errors, validation, security, cache, pagination
│   ├── workers/          # arq settings and jobs
│   └── seeds/            # seed runner and seed items
└── tests/                # layout set by task 3.3
```

## Modules and where a new feature goes
1. The modules are `account`, `account_profile`, `account_role`, `auth`, `files` and `notifier`. Each has `<module>.py` in `routers/`, `schemas/`, `models/` and `services/`; the one exception is `models/`, where the files are `file.py`, `notification.py` and `system.py` (`DeletedHistory`, `Migration`; task 2.3). A new module adds `<module>.py` to the layers it needs; do not create a package per feature.
2. Extra files inside a layer (for example `services/otp.py`) are fine when a task names them. A new top-level module or a new layer is not: it needs an ADR.
3. Cross-cutting code goes in `core/`, one module per concern (`core/db.py`, `core/errors.py`, ...). Do not put it in a layer.

## Import direction
4. `routers` use `services`, `schemas` and `dependencies`. `services` use `models`, `schemas`, `core` and `config`. `models` import only from `core` and from sibling models (relationships). `core` imports from no layer and may read `config`. `schemas` import nothing from `services`, `models` or `routers`. `dependencies` use `services`, `core` and `config`. `workers` and `seeds` use `services`, `models`, `core` and `config`. `config` may be imported by anything except `models` and `schemas`. A module may import siblings in its own layer if there is no cycle. The full statement is in ADR-0011.
5. No business logic in a router: it parses the request, calls a service, returns a schema. A response model is never an ORM object.
6. A service never receives a framework object (request, response, headers, `Depends`). Plain values, models and Pydantic `schemas` (plain data) may go in and out (ADR-0003, ADR-0011).
7. No module imports from `routers` except `main.py`. A circular import means the logic is in the wrong layer.

## Tests
8. The layout inside `tests/` is not decided here: task 3.3 sets it, and the rules are in `testing.md` and `testing-python.md`. Note for 1.4 and 3.3: `testing-python.md` names a test file `tests/test_<module>.py`, which would collide for one module name across four layers (a router and a service both called `account`); the layout must separate them.

## Migrations
9. `migrations/` is tooling beside `app/`, not a layer (ADR-0017). `migrations/env.py` may import `app.config`, `app.core.db` and `app.models`; nothing in `app/` imports from `migrations/`. A revision in `migrations/versions/` imports nothing from `app`, names every table and column itself, and is never edited once merged: a schema change is a new revision.
