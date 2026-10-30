# ADR-0004 — SQLAlchemy 2 (async) with Alembic on PostgreSQL

- **Date:** 2026-10-29
- **Status:** accepted; the soft-delete bullet about mixins is superseded by [ADR-0014](ADR-0014-opt-in-column-mixins.md)
- **Deciders:** volodymyr
- **Ticket:** POC-1.1
- **Supersedes:** the ORM half of Node ADR-0001 (Use Prisma as the ORM, with a Redis-backed read cache). The Redis cache half is not decided here; task 9.1 decides it. Decision D3 of the scope doc.

## Context
The Node base reaches PostgreSQL (PostGIS enabled) through Prisma. Python needs its own data layer. The scope doc wants the Python service to keep the Node base's table and column names, so a fork can read the same data model.

## Decision
- ORM: SQLAlchemy 2 in async mode with the `asyncpg` driver. One session per request, provided as a FastAPI dependency.
- Migrations: Alembic with an async environment. Revision `0001_init` is the final state of the four Prisma migrations.
- Table and column names are a **target** of parity with the Prisma schema (quoted identifiers such as `"Account"` and `"createdAt"`). Task 2.5 proves it by diffing `pg_dump --schema-only` of a Prisma-migrated and an Alembic-migrated database; this ADR does not claim it before then.
- Soft deletes only (rule P6): a shared mixin carries only the `deleted` flag. Ids and timestamps follow each Prisma model and are declared per table: for example `AccountRole`, `AccountIdentity` and `AccountProfile` have no `createdAt`/`updatedAt`, `Account.updatedAt` is nullable, and `AccountOnRole` has a composite key instead of an `id`.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Prisma Client Python | the scope doc calls it no longer maintained (to be re-checked in task 2.1 before relying on that reason) |
| SQLModel | adds a layer over SQLAlchemy and Pydantic with no feature this base needs |
| Tortoise ORM or raw SQL only | smaller ecosystem, no Alembic-grade migration story |

## Consequences
- Positive: mature ORM and migration tool; async end to end.
- Accepted cost: a hand-written initial revision; any difference from the Prisma schema must be listed in the parity task.
- Follow-ups: tasks 2.1 to 2.5. The naming convention and the mixins live in `app/core/db.py` (task 2.1, ADR-0014). The read cache (task 9.1) wraps service reads, not the ORM.

## Revisit when
Schema parity with the Node base stops mattering, or SQLAlchemy async cannot meet a requirement.
