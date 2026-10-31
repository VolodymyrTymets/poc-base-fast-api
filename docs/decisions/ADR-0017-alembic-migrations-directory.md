# ADR-0017 — Alembic lives in `migrations/` at the repo root

- **Date:** 2026-10-31
- **Status:** accepted; the task 2.5 diff wording is superseded by [ADR-0019](ADR-0019-schema-parity-not-diffed.md)
- **Deciders:** volodymyr
- **Ticket:** POC-2.4
- **Extends:** [ADR-0011](ADR-0011-project-structure.md) (the layout of `app/`, which says nothing about tooling beside it) and [ADR-0004](ADR-0004-data-layer-sqlalchemy-alembic.md) (Alembic with an async environment, a hand-written `0001_init`). The scope row's path `api/alembic/**` is stale: ADR-0010 and ADR-0011 drop `api/`.

## Context
Task 2.4 adds Alembic. ADR-0011 fixes the tree of `app/` and says a new top-level module or layer needs an ADR; a migration environment is neither, but it is a new top-level directory, and it is a new importer of `app` (`env.py` reads the settings, the engine factory and the models). The scope row names the directory `alembic/`, which is also the name of the installed package, so a directory called `alembic` at the repo root risks shadowing it for mypy and for any tool that puts the repo root on the import path.

## Decision
- `alembic.ini` and `migrations/` sit at the repo root, next to `pyproject.toml`. They are not part of the `app` wheel (the build backend packages only `app`); a container image (task 11.1) copies them explicitly.
- `alembic.ini` holds no database URL. `migrations/env.py` reads `Settings.database_url` through `app.config.get_settings()` and builds its engine with `app.core.db.create_engine`, so migrations use the same UTC session time zone as the app and a URL is never written in a tracked file.
- Import rule, an addition to ADR-0011's direction list: `migrations/env.py` may import `app.config`, `app.core.db` and `app.models` (it needs the metadata). A revision under `migrations/versions/` imports nothing from `app`: it names every table and column itself, so a later model change cannot change what an applied revision builds.
- Revisions are hand-written (ADR-0004) and never edited once merged; a schema change is a new revision. `migrations/versions/**` is an ask-first path for that reason.
- `alembic check` runs with `compare_type` and `compare_server_default` on, and skips only the table PostGIS itself creates (`spatial_ref_sys`). Any other table the models lack still shows as a difference.
- `0001_init` creates the `postgis` extension and its downgrade leaves the extension in place, because other objects in the database may depend on it.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| `alembic/` (the scope row) | same name as the installed package; risks shadowing it |
| `app/migrations/` | migrations are tooling, not application code, and `app` must not import them; the import direction of ADR-0011 would need an exception in the other direction |
| `api/alembic/` | there is no `api/` (ADR-0010, ADR-0011) |
| Autogenerate `0001_init` from the models | the revision must equal the Node base's final schema (task 2.5 proves it), and a revision generated from the models would follow them silently; `alembic check` is what compares the two |
| A custom engine in `env.py` | a second place to keep the UTC session rule |

## Consequences
- Positive: one command builds the schema; `alembic check` fails when a model and the revision drift apart; a frozen revision cannot be changed by a refactor.
- Accepted cost: `env.py` is code outside `app/` that depends on it; a rename in `app.core.db` has to be followed there. A container build must remember `alembic.ini` and `migrations/`.
- Follow-ups: task 2.5 diffs `pg_dump --schema-only` of a Prisma-migrated and an Alembic-migrated database; task 3.1 builds the test database from this revision; task 11.1 copies the directory into the image.

## Revisit when
A second deployable needs its own migrations, or the models move out of `app/`.
