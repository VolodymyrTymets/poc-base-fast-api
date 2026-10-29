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
├── .env                  # secrets, never committed
├── app/
│   ├── main.py           # FastAPI(), include_router, nothing else
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
1. The modules are `account`, `account_profile`, `account_role`, `auth`, `files` and `notifier`. Each has `<module>.py` in `routers/`, `schemas/`, `models/` and `services/`; the one exception is `models/`, where the files are `file.py` and `notification.py` (task 2.3). A new module adds `<module>.py` to the layers it needs; do not create a package per feature.
2. Extra files inside a layer (for example `services/otp.py`) are fine when a task names them. A new top-level module or a new layer is not: it needs an ADR.
3. Cross-cutting code goes in `core/`, one module per concern (`core/db.py`, `core/errors.py`, ...). Do not put it in a layer.

## Import direction
4. `routers` use `services`, `schemas` and `dependencies`. `services` use `models`, `schemas` and `core`. `models` import only from `core`. `core` imports from no layer. `workers` and `seeds` use `services` and `models`. `main.py` only wires.
5. No business logic in a router: it parses the request, calls a service, returns a schema. A response model is never an ORM object.
6. A service never receives a framework object (request, response, `Depends`); it takes plain values and returns plain values or models (ADR-0003).
7. No module imports from `routers` except `main.py`. A circular import means the logic is in the wrong layer.

## Tests
8. The layout inside `tests/` is not decided here: task 3.3 sets it, and the rules are in `testing.md` and `testing-python.md`.
